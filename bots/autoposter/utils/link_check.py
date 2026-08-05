"""Проверка жизни Telegram-ссылки и подмена на запасную."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Optional

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramUnauthorizedError

log = logging.getLogger("link_check")

# Кеш проверок: {username_lower: (is_alive, checked_at)}
_cache: dict[str, tuple[bool, float]] = {}
_CACHE_TTL = 300.0  # 5 минут

# t.me/<username>?... или t.me/<username>/... или https://t.me/<username>
_TG_RE = re.compile(r"(?:https?://)?t\.me/(?:@?)([A-Za-z0-9_]{4,32})", re.I)


def extract_tg_username(url: str) -> Optional[str]:
    """Извлекает username из t.me/<username>... ссылки. None если не t.me."""
    if not url:
        return None
    m = _TG_RE.search(url)
    if not m:
        return None
    name = m.group(1)
    # отсекаем системные пути типа /joinchat, /addstickers — это не боты
    if name.lower() in {"joinchat", "addstickers", "share", "proxy", "iv", "+", "c", "s"}:
        return None
    return name


async def is_username_alive(main_bot: Bot, username: str) -> bool:
    """Проверяет существование @username через основной бот.
    Двойная проверка с паузой 30 сек чтобы не среагировать на временный сбой.
    Кеш — 5 минут.
    """
    key = username.lower()
    now = time.time()
    cached = _cache.get(key)
    if cached and (now - cached[1]) < _CACHE_TTL:
        return cached[0]

    async def _one_check() -> Optional[bool]:
        try:
            await main_bot.get_chat(f"@{username}")
            return True
        except TelegramBadRequest as e:
            msg = str(e).lower()
            if "not found" in msg or "chat_not_found" in msg or "username_invalid" in msg:
                return False
            log.warning("get_chat(@%s) bad request: %s", username, e)
            return None
        except TelegramUnauthorizedError:
            # сам main_bot мёртв — не наша забота тут, не считаем что @username мёртв
            return None
        except Exception as e:
            log.warning("get_chat(@%s): %s", username, e)
            return None

    r1 = await _one_check()
    if r1 is True:
        _cache[key] = (True, now)
        return True
    if r1 is False:
        # подтверждаем второй проверкой
        await asyncio.sleep(30)
        r2 = await _one_check()
        if r2 is False:
            _cache[key] = (False, time.time())
            return False
        # вторая проверка не подтвердила — считаем что жив, в кеш не пишем
        return True
    # None — неопределённость, считаем что жив (не штрафуем за неоднозначный ответ)
    return True


def _replace_url_everywhere(text: str | None, buttons_raw: str | None,
                             old_url: str, new_url: str) -> tuple[str | None, str | None]:
    """Меняет old_url → new_url в html-тексте (href) и в buttons[].url."""
    new_text = text or ""
    if new_text:
        new_text = re.sub(
            r'href=([\'"])' + re.escape(old_url) + r'\1',
            lambda m: f'href={m.group(1)}{new_url}{m.group(1)}',
            new_text,
        )
    try:
        btns = json.loads(buttons_raw) if buttons_raw else []
    except Exception:
        btns = []
    for b in btns:
        if isinstance(b, dict) and b.get("url") == old_url:
            b["url"] = new_url
    return (new_text or None), (json.dumps(btns, ensure_ascii=False) if btns else None)


def _all_urls_in_post(post) -> list[str]:
    urls: list[str] = []
    seen = set()
    text = post["text"] or ""
    for m in re.finditer(r'href=[\'"]([^\'"]+)[\'"]', text):
        u = m.group(1)
        if u not in seen:
            seen.add(u); urls.append(u)
    try:
        btns = json.loads(post["buttons"]) if post["buttons"] else []
    except Exception:
        btns = []
    for b in btns:
        u = b.get("url") if isinstance(b, dict) else None
        if u and u not in seen:
            seen.add(u); urls.append(u)
    return urls


async def repair_post_links(db, main_bot: Bot, post, admin_ids: list[int]) -> str:
    """Проверяет все t.me-ссылки поста. Подменяет мёртвые на живые из backup_urls.
    Возвращает:
      "ok"      — всё живо или починили,
      "blocked" — есть мёртвая, а в запасе живых нет (постинг не должен идти).
    """
    urls = _all_urls_in_post(post)
    try:
        backup = json.loads(post["backup_urls"]) if post["backup_urls"] else []
    except Exception:
        backup = []

    text = post["text"]
    buttons = post["buttons"]
    notifications: list[tuple[str, str]] = []   # (old, new)
    blocked = False
    all_dead = []

    for url in urls:
        uname = extract_tg_username(url)
        if uname is None:
            continue  # не t.me — пропускаем
        alive = await is_username_alive(main_bot, uname)
        if alive:
            continue
        # ссылка мёртвая — ищем живую запасную
        replacement = None
        new_backup = list(backup)
        while new_backup:
            cand = new_backup[0]
            cand_uname = extract_tg_username(cand)
            if cand_uname is None:
                # внешняя ссылка в запасе — нечего проверить, считаем живой
                replacement = cand
                new_backup.pop(0)
                break
            cand_alive = await is_username_alive(main_bot, cand_uname)
            if cand_alive:
                replacement = cand
                new_backup.pop(0)
                break
            else:
                # тоже мёртвая — выкидываем из запаса
                new_backup.pop(0)
        if replacement is None:
            blocked = True
            all_dead.append(url)
            continue
        # подмена
        text, buttons = _replace_url_everywhere(text, buttons, url, replacement)
        new_backup.append(url)   # мёртвая ссылка уходит в конец запаса
        backup = new_backup
        notifications.append((url, replacement))

    if notifications or blocked:
        await db.update_post(
            post["id"],
            text=text,
            buttons=buttons,
            backup_urls=(json.dumps(backup, ensure_ascii=False) if backup else None),
        )

    # уведомления
    if notifications:
        body = "\n".join(
            f"  • <code>{o}</code>\n      → <code>{n}</code>"
            for o, n in notifications
        )
        text_msg = (
            f"⚠️ <b>Подмена ссылок в посте {post['id']}</b>\n\n{body}"
        )
        for aid in admin_ids:
            try:
                await main_bot.send_message(aid, text_msg)
            except Exception as e:
                log.warning("уведомление %s: %s", aid, e)

    if blocked:
        body = "\n".join(f"  • <code>{u}</code>" for u in all_dead)
        text_msg = (
            f"🚫 <b>Постинг приостановлен</b>\n\n"
            f"В посте {post['id']} мёртвые ссылки, а запасных живых нет:\n"
            f"{body}\n\n"
            f"Пополни 🆘 запасной пул поста и снова запусти автопостинг."
        )
        for aid in admin_ids:
            try:
                await main_bot.send_message(aid, text_msg)
            except Exception as e:
                log.warning("уведомление %s: %s", aid, e)
        return "blocked"

    return "ok"
