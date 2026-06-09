#!/bin/bash
# Фикс цветов кнопок: только 3 цвета согласно Bot API 9.4 (Primary/Success/Danger),
# плюс стандартный белый. Никакого Secondary (серого) в API нет.
set -e
cd /opt/bot

echo "==> Патчу utils/helpers.py..."
python3 /opt/bot/fix_colors.py

echo "==> Перезапускаю бот..."
systemctl restart bot
sleep 2
systemctl status bot --no-pager | head -8

echo "==> Готово."
