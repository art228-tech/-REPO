"""Сторож ссылок: периодически проверяет, жив ли бот/аккаунт, на который ведёт
ссылка из шага. Если ссылка «умерла» (бот удалён/недоступен) и у неё заданы
запасные ссылки — автоматически подставляет первую рабочую запасную в текст и
кнопки шага и уведомляет администраторов.

Структура в cfg шага:
    cfg["link_backups"] = { "<основная_ссылка>": ["<запас1>", "<запас2>", ...] }
Если link_backups пуст — шаг не трогаем (всё как обычно).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest

log = logging.getLogger("link_guard")

# Интервал проверки (сек). Можно переопределить в .env: LINK_GUARD_INTERVAL
CHECK_INTERVAL = int(os.getenv("LINK_GUARD_INTERVAL", "120"))

# Для ТОЧНОГО детекта заморозки нужен MTProto (Telethon) + api_id/api_hash.
_API_ID = os.getenv("TG_API_ID") or ""
_API_HASH = os.getenv("TG_API_HASH") or ""

_USERNAME_RE = re.compile(
    r"(?:t\.me/|telegram\.me/|domain=|@)([A-Za-z0-9_]{4,})", re.I
)

# Один общий MTProto-клиент (ленивая инициализация на токене конструктора).
_tele = None
_tele_lock = asyncio.Lock()


async def _get_tele(bot_token: str):
    """Возвращает запущенный Telethon-клиент (бот-сессия) или None, если
    api_id/api_hash не заданы либо Telethon недоступен."""
    global _tele
    if not (_API_ID and _API_HASH):
        return None
    if _tele is not None:
        return _tele
    async with _tele_lock:
        if _tele is not None:
            return _tele
        try:
            from telethon import TelegramClient
            from telethon.sessions import StringSession
            cli = TelegramClient(StringSession(), int(_API_ID), _API_HASH)
            await cli.start(bot_token=bot_token)
            _tele = cli
            log.info("link_guard: MTProto-проверка включена (точный детект заморозки)")
        except Exception as e:
            log.warning("link_guard: MTProto недоступен (%s) — детект только удаления", e)
            _tele = None
    return _tele


async def _check_mtproto(client, username: str) -> str:
    """'alive' | 'dead' | 'unknown' через MTProto (видит deleted/restricted/scam/fake)."""
    try:
        from telethon import errors
        try:
            ent = await client.get_entity(username)
        except (errors.UsernameNotOccupiedError, errors.UsernameInvalidError, ValueError):
            return "dead"
        except errors.FloodWaitError:
            return "unknown"
        if getattr(ent, "deleted", False):
            return "dead"
        if getattr(ent, "restricted", False):  # заморожен/ограничен
            return "dead"
        if getattr(ent, "scam", False) or getattr(ent, "fake", False):
            return "dead"
        return "alive"
    except Exception as e:
        log.debug("_check_mtproto(%s): %s", username, e)
        return "unknown"


def extract_bot_username(url: str | None) -> str | None:
    """Достаёт username из ссылки вида t.me/Bot?start=... или @Bot.
    Возвращает None для инвайт-ссылок (t.me/+...), c/-ссылок и не-username."""
    if not url:
        return None
    if "t.me/+" in url or "/joinchat/" in url or "t.me/c/" in url:
        return None
    m = _USERNAME_RE.search(url)
    return m.group(1) if m else None


async def is_url_alive(bot: Bot, url: str) -> bool | None:
    """True — жив, False — точно мёртв (username не найден), None — проверить нельзя."""
    uname = extract_bot_username(url)
    if not uname:
        return None
    try:
        await bot.get_chat("@" + uname)
        return True
    except TelegramBadRequest as e:
        s = str(e).lower()
        if any(k in s for k in ("not found", "username", "invalid", "no user", "not occupied")):
            return False
        return None
    except Exception as e:
        log.debug("is_url_alive(%s): %s", url, e)
        return None


async def check_link(main_bot: Bot, url: str) -> str:
    """'alive' | 'dead' | 'unknown'. Использует MTProto (точно, ловит заморозку),
    если заданы api_id/api_hash; иначе — Bot API (только удаление)."""
    uname = extract_bot_username(url)
    if not uname:
        return "unknown"  # не username-ссылка — проверить нельзя
    cli = await _get_tele(main_bot.token)
    if cli is not None:
        return await _check_mtproto(cli, uname)
    res = await is_url_alive(main_bot, url)
    return {True: "alive", False: "dead", None: "unknown"}[res]


def _replace_link_in_cfg(cfg: dict, old: str, new: str) -> dict:
    text = cfg.get("text") or ""
    if text:
        cfg["text"] = re.sub(
            r"href=(['\"])" + re.escape(old) + r"\1",
            lambda m: f"href={m.group(1)}{new}{m.group(1)}",
            text,
        )
    for b in (cfg.get("buttons") or []):
        if isinstance(b, dict) and b.get("url") == old:
            b["url"] = new
    return cfg


async def _notify(bot: Bot, admin_ids, text: str) -> None:
    for aid in admin_ids or []:
        try:
            await bot.send_message(aid, text, disable_web_page_preview=True)
        except Exception:
            pass


async def link_guard_loop(main_bot: Bot, admin_ids, interval: int = CHECK_INTERVAL) -> None:
    from database import get_db

    log.info("link_guard запущен, интервал %s сек", interval)
    while True:
        try:
            db = get_db()
            cur = await db.conn.execute("SELECT id, config FROM steps")
            rows = await cur.fetchall()
            for r in rows:
                sid, cfg_raw = r[0], r[1]
                try:
                    cfg = json.loads(cfg_raw)
                except Exception:
                    continue
                lb = cfg.get("link_backups") or {}
                if not lb:
                    continue
                changed = False
                for url in list(lb.keys()):
                    backups = lb.get(url) or []
                    if not backups:
                        continue
                    if await check_link(main_bot, url) != "dead":
                        continue  # жива или непроверяемо — не трогаем
                    # основная ссылка мертва — ищем первую рабочую запасную
                    chosen = None
                    for b in backups:
                        if await check_link(main_bot, b) != "dead":
                            chosen = b
                            break
                    if chosen is None:
                        await _notify(
                            main_bot, admin_ids,
                            f"⚠️ Шаг #{sid}: ссылка умерла, но рабочих запасных нет:\n{url}",
                        )
                        continue
                    cfg = _replace_link_in_cfg(cfg, url, chosen)
                    remaining = [x for x in backups if x != chosen]
                    lb.pop(url, None)
                    lb[chosen] = remaining
                    cfg["link_backups"] = lb
                    changed = True
                    await _notify(
                        main_bot, admin_ids,
                        f"🔁 Шаг #{sid}: основная ссылка перестала работать — заменил на запасную.\n\n"
                        f"Было: {url}\nСтало: {chosen}\n\nОсталось запасных: {len(remaining)}",
                    )
                if changed:
                    await db.update_step(sid, config=json.dumps(cfg, ensure_ascii=False))
        except Exception as e:
            log.exception("link_guard: %s", e)
        await asyncio.sleep(interval)
