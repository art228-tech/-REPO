#!/bin/bash
# Применяет правки в bots/scenario.py:
# 1. После исчерпания дублей ждать delete_timer, удалить последнее сообщение, потом advance

set -e

FILE=/opt/bot/bots/scenario.py

python3 <<'PYEOF'
import re

with open('/opt/bot/bots/scenario.py', 'r', encoding='utf-8') as f:
    src = f.read()

# Старый блок завершения дублей
old = '''                # Лимит достигнут — пропускаем шаг
                user = await db.get_user(user_id)
                if user and user["current_step_order"] == step["step_order"]:
                    # Запускаем advance отдельной задачей, потому что
                    # advance вызовет _cancel_dup, который отменит нас же.
                    asyncio.create_task(self.advance(bot, bot_record, user_id))'''

new = '''                # Лимит достигнут. Даём юзеру увидеть последнее
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

if old not in src:
    print("OLD block not found in scenario.py — already patched?")
else:
    src = src.replace(old, new)
    with open('/opt/bot/bots/scenario.py', 'w', encoding='utf-8') as f:
        f.write(src)
    print("scenario.py patched OK")
PYEOF

echo "done"
