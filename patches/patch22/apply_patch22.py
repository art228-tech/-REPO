#!/usr/bin/env python3
"""
Патч 22: после достижения лимита дублей сценарий идёт к следующему шагу
СРАЗУ. Последнее задублированное сообщение удаляется фоном через
delete_timer секунд (не блокируя переход).

Было: код ждал delete_timer ПЕРЕД advance — при delete_timer=300
следующий шаг приходил через 5 минут.
"""
from pathlib import Path

ROOT = Path("/opt/bot")  # для друга — /opt/friend_bot
SN = ROOT / "bots/scenario.py"

src = SN.read_text(encoding="utf-8")

old = '''                # Лимит достигнут. Даём юзеру увидеть последнее
                # дублирование (ждём delete_timer), удаляем его и только
                # потом продвигаем сценарий.
                user = await db.get_user(user_id)
                if not user or user["current_step_order"] != step["step_order"]:
                    return
                del_after = (bot_record["delete_timer"] or 10)
                await asyncio.sleep(del_after)
                user = await db.get_user(user_id)
                if not user or user["current_step_order"] != step["step_order"]:
                    return
                if user["last_message_id"]:
                    await safe_delete_message(
                        bot, user["last_message_chat_id"], user["last_message_id"]
                    )
                # Запускаем advance отдельной задачей, потому что
                # advance вызовет _cancel_dup, который отменит нас же.
                asyncio.create_task(self.advance(bot, bot_record, user_id))'''

new = '''                # Лимит дублей достигнут.
                user = await db.get_user(user_id)
                if not user or user["current_step_order"] != step["step_order"]:
                    return
                # Последнее задублированное сообщение удаляем ФОНОМ через
                # delete_timer секунд — не блокируя переход к след. шагу.
                _last_chat = user["last_message_chat_id"]
                _last_msg = user["last_message_id"]
                if _last_msg:
                    _dt = (bot_record["delete_timer"] or 10)

                    async def _del_last(c=_last_chat, m=_last_msg, d=_dt):
                        try:
                            await asyncio.sleep(d)
                            await safe_delete_message(bot, c, m)
                        except asyncio.CancelledError:
                            pass
                    asyncio.create_task(_del_last())
                # Сценарий идёт дальше СРАЗУ. advance отдельной задачей,
                # потому что advance вызовет _cancel_dup → отменит нас же.
                asyncio.create_task(self.advance(bot, bot_record, user_id))'''

if old not in src:
    raise SystemExit(
        "Блок «Лимит достигнут» не совпал. Покажи "
        "`sed -n '508,528p' /opt/bot/bots/scenario.py` — подгоню патч."
    )

src = src.replace(old, new, 1)

# Заодно убираем все debug-логи [DUP], которые ставились при диагностике
import re
src = re.sub(r' *import logging as _l\d?; _l\d?\.getLogger\("scenario"\)\.warning\("\[DUP\][^\n]*\n', '', src)

SN.write_text(src, encoding="utf-8")
print("  ✓ bots/scenario.py — переход после дублей сразу, удаление фоном")
print("  ✓ debug-логи [DUP] убраны")
print("\n✅ Патч 22 применён. Перезапусти: systemctl restart bot")
