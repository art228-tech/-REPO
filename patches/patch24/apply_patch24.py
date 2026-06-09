#!/usr/bin/env python3
"""
Патч 24: отключение превью ссылок (link preview) в сообщениях сценария.
Telegram разворачивает картинку/описание сайта под текстом со ссылкой —
теперь этого не будет.
"""
from pathlib import Path

ROOT = Path("/opt/bot")  # для друга — /opt/friend_bot
HL = ROOT / "utils/helpers.py"

src = HL.read_text(encoding="utf-8")

# 1. Импорт LinkPreviewOptions
if "LinkPreviewOptions" not in src:
    # добавляем к импорту из aiogram.types
    if "from aiogram.types import" in src:
        src = src.replace(
            "from aiogram.types import",
            "from aiogram.types import LinkPreviewOptions,",
            1,
        )
    else:
        # на всякий — отдельной строкой после первого импорта
        src = src.replace(
            "import", "from aiogram.types import LinkPreviewOptions\nimport", 1
        )

# 2. Хелпер-константа отключённого превью + подмена send_message
# Оба текстовых send_message получают link_preview_options.
old1 = '''            msg = await bot.send_message(
                chat_id, text or "...", reply_markup=reply_markup
            )
            # Reply keyboard приходит через отдельное сообщение'''
new1 = '''            msg = await bot.send_message(
                chat_id, text or "...", reply_markup=reply_markup,
                link_preview_options=LinkPreviewOptions(is_disabled=True),
            )
            # Reply keyboard приходит через отдельное сообщение'''
if old1 not in src:
    raise SystemExit("send_message #1 не найден — структура helpers иная")
src = src.replace(old1, new1, 1)

old2 = '''        markup = reply_markup if reply_markup is not None else keyboard_markup
        msg = await bot.send_message(chat_id, text or "...", reply_markup=markup)
        return msg.message_id'''
new2 = '''        markup = reply_markup if reply_markup is not None else keyboard_markup
        msg = await bot.send_message(
            chat_id, text or "...", reply_markup=markup,
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )
        return msg.message_id'''
if old2 not in src:
    raise SystemExit("send_message #2 не найден — структура helpers иная")
src = src.replace(old2, new2, 1)

HL.write_text(src, encoding="utf-8")
print("  ✓ utils/helpers.py — превью ссылок отключено")
print("\n✅ Патч 24 применён. Перезапусти: systemctl restart bot")
