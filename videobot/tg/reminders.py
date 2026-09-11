"""Напоминание про просмотры — ровно одно на ролик.

Через сутки после того, как человек скачал ролик, бот один раз спрашивает
просмотры. Ровно один: ролик могли и не выложить, и долбить человека каждый
день незачем.

Сутки считаются от скачивания, а не от выдачи: ролик мог пролежать назначенным
неделю, и напоминание пришло бы раньше, чем человек вообще увидел файл.
"""
from __future__ import annotations

import asyncio
from collections import defaultdict

from aiogram import Bot

from ..db import Base
from ..logs import get_logger

log = get_logger("напоминания")

CHECK_EVERY_S = 600.0


async def send_due(bot: Bot, base: Base, hours: int) -> int:
    """Шлёт напоминания тем, у кого подошёл срок. Возвращает число роликов."""
    due = base.due_for_reminder(hours)
    if not due:
        return 0

    by_person: dict[int, list] = defaultdict(list)
    for row in due:
        if row["owner_id"]:
            by_person[row["owner_id"]].append(row)

    sent = 0
    for tg_id, rows in by_person.items():
        names = "\n".join(f"• {row['name']}" for row in rows[:20])
        more = f"\n…и ещё {len(rows) - 20}" if len(rows) > 20 else ""
        text = (
            f"Прошли сутки. Впишите просмотры, если выкладывали:\n\n{names}{more}\n\n"
            "Это в меню, раздел «История и просмотры». Напомню только один раз."
        )
        try:
            await bot.send_message(tg_id, text)
        except Exception as exc:  # noqa: BLE001 - человек мог заблокировать бота
            log.warning("Напоминание для %d не ушло: %s", tg_id, exc)
            # Отмечаем всё равно: иначе бот будет упираться в него вечно.

        for row in rows:
            base.mark_reminded(row["id"])
            sent += 1

    log.info("Напоминаний отправлено по %d роликам", sent)
    return sent


async def loop(bot: Bot, base: Base, hours: int) -> None:
    while True:
        try:
            await send_due(bot, base, hours)
        except Exception as exc:  # noqa: BLE001 - цикл не должен умирать
            log.error("Напоминания сорвались: %s", exc)
        await asyncio.sleep(CHECK_EVERY_S)
