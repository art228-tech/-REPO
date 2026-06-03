#!/bin/bash
# Установщик патча 2: нативные цвета кнопок (Bot API 9.4) + премиум-стикеры в
# кнопках + фикс дублирования.
#
# Запускать на сервере, в /opt/bot, ПОСЛЕ распаковки bot_patch2.zip туда же.

set -e

cd /opt/bot

echo "==> 1) Обновляем aiogram до 3.28.2 (требуется для Bot API 9.4)"
./venv/bin/pip install -q --upgrade 'aiogram==3.28.2'

echo "==> 2) Перезапускаем бот"
systemctl restart bot
sleep 2
systemctl status bot --no-pager | head -8

echo "==> Готово."
