"""Фоновая проверка прав приветок в спонсорских каналах.
Раз в SPONSOR_CHECK_INTERVAL секунд проходит по всем шагам ОП всех приветок,
проверяет права и шлёт алерт админам если что-то сломалось.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from database import get_db
from utils.sponsor_check import check_sponsor_access

log = logging.getLogger("sponsor_monitor")

SPONSOR_CHECK_INTERVAL = 600  # 10 минут
# Чтобы не спамить одинаковыми алертами — храним последний код проблемы в памяти
_last_state: dict[tuple[int, int], str] = {}  # (bot_id, channel_id) -> reason


async def _notify_admins(main_bot, admin_ids: list[int], text: str) -> None:
    for admin_id in admin_ids:
        try:
            await main_bot.send_message(admin_id, text)
        except Exception as e:
            log.warning("Не отправилось админу %s: %s", admin_id, e)


async def _check_one_bot(main_bot, admin_ids: list[int], bot_row, greeter_bot) -> None:
    db = get_db()
    cur = await db.conn.execute(
        "SELECT id, config FROM steps WHERE bot_id=? AND step_type='op'",
        (bot_row["id"],),
    )
    steps = await cur.fetchall()
    for step in steps:
        try:
            cfg = json.loads(step["config"])
        except Exception:
            continue
        for sp in cfg.get("sponsors", []):
            if not sp.get("check"):
                continue  # не обязательный — пропускаем
            cid = sp.get("channel_id")
            if not cid:
                continue
            need_invite = bool(sp.get("request_mode"))
            res = await check_sponsor_access(
                greeter_bot, int(cid), require_invite_users=need_invite
            )
            key = (bot_row["id"], int(cid))
            if not res["ok"]:
                # Сломано. Если про эту же причину уже сообщали — не дублируем.
                prev = _last_state.get(key)
                if prev == res["reason"]:
                    continue
                _last_state[key] = res["reason"]
                title = sp.get("title") or sp.get("button_text") or str(cid)
                bot_title = bot_row["title"] or f"приветка #{bot_row['id']}"
                text = (
                    f"⚠️ <b>Спонсор сломался</b>\n\n"
                    f"Приветка: <b>{bot_title}</b>\n"
                    f"Спонсор: <b>{title}</b> (<code>{cid}</code>)\n"
                    f"Причина: {res['reason']}\n\n"
                    "Проверь админ-права приветки и ссылку."
                )
                await _notify_admins(main_bot, admin_ids, text)
            else:
                # Восстановилось — если раньше был алерт, шлём «всё ок»
                if key in _last_state:
                    del _last_state[key]
                    title = sp.get("title") or sp.get("button_text") or str(cid)
                    bot_title = bot_row["title"] or f"приветка #{bot_row['id']}"
                    text = (
                        f"✅ <b>Спонсор восстановлен</b>\n\n"
                        f"Приветка: <b>{bot_title}</b>\n"
                        f"Спонсор: <b>{title}</b> (<code>{cid}</code>)"
                    )
                    await _notify_admins(main_bot, admin_ids, text)


async def sponsor_monitor_loop(main_bot, admin_ids: list[int]) -> None:
    """Главный цикл. Запускается фоновой задачей в main.py."""
    from bots.manager import get_manager
    log.info("Запущен sponsor_monitor, интервал %s сек", SPONSOR_CHECK_INTERVAL)
    while True:
        try:
            db = get_db()
            # Чистим устаревшие заявки, чтобы таблица не пухла
            try:
                _removed = await db.cleanup_old_pending(30)
                if _removed:
                    log.info("Удалено старых заявок: %s", _removed)
            except Exception as _e:
                log.warning("cleanup_old_pending: %s", _e)
            bots = await db.list_greeting_bots()
            mgr = get_manager()
            for bot_row in bots:
                greeter_bot = mgr.get_bot_instance(bot_row["id"])
                if greeter_bot is None:
                    continue
                await _check_one_bot(main_bot, admin_ids, bot_row, greeter_bot)
        except Exception as e:
            log.exception("ошибка в sponsor_monitor: %s", e)
        await asyncio.sleep(SPONSOR_CHECK_INTERVAL)
