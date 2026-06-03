#!/usr/bin/env python3
"""
Патч 11: при дублировании старое сообщение удаляется не мгновенно,
а через delete_timer секунд после отправки дубля (как при переходе
к следующему шагу). Так в чате не бывает «пустого окна».
"""
from pathlib import Path

ROOT = Path("/opt/bot")
SN = ROOT / "bots/scenario.py"

src = SN.read_text(encoding="utf-8")

old = '''                    # Дублируем сообщение
                    count += 1
                    await db.update_user(user_id, duplicate_count=count)
                    # Удаляем старое
                    if user["last_message_id"]:
                        await safe_delete_message(
                            bot, user["last_message_chat_id"], user["last_message_id"]
                        )
                    await self._send_step_to_user(
                        bot, bot_record, user_id,
                        step_order=user["current_step_order"], is_duplicate=True,
                    )'''

new = '''                    # Дублируем сообщение
                    count += 1
                    await db.update_user(user_id, duplicate_count=count)
                    # Запоминаем id старого сообщения ДО отправки дубля
                    # (отправка перезапишет last_message_id на новое).
                    _old_chat = user["last_message_chat_id"]
                    _old_msg = user["last_message_id"]
                    # Сначала отправляем дубль — чат ни секунды не пустой.
                    await self._send_step_to_user(
                        bot, bot_record, user_id,
                        step_order=user["current_step_order"], is_duplicate=True,
                    )
                    # Старое удаляем отложенно — через delete_timer секунд.
                    if _old_msg:
                        _delay = bot_record["delete_timer"] or 10

                        async def _del_old(c=_old_chat, m=_old_msg, d=_delay):
                            try:
                                await asyncio.sleep(d)
                                await safe_delete_message(bot, c, m)
                            except asyncio.CancelledError:
                                pass
                        asyncio.create_task(_del_old())'''

if old not in src:
    raise SystemExit("Не нашёл блок дубля — структура отличается. Покажи "
                     "`sed -n '404,417p' /opt/bot/bots/scenario.py`")

src = src.replace(old, new, 1)
SN.write_text(src, encoding="utf-8")
print("  ✓ bots/scenario.py — старое сообщение при дубле удаляется отложенно")
print("\n✅ Патч 11 применён. Перезапусти: systemctl restart bot")
