#!/usr/bin/env bash
# Авто-установка на свежий Ubuntu 22.04 / 24.04.
# Запускать из-под root: bash install.sh

set -e

if [ "$EUID" -ne 0 ]; then
    echo "Запусти от root: sudo bash install.sh"
    exit 1
fi

echo "==> apt update + зависимости…"
apt update
apt install -y python3.12 python3.12-venv python3-pip nginx certbot python3-certbot-nginx unzip || \
    apt install -y python3 python3-venv python3-pip nginx certbot python3-certbot-nginx unzip

INSTALL_DIR="${INSTALL_DIR:-/opt/bot}"
echo "==> Создаю $INSTALL_DIR…"
mkdir -p "$INSTALL_DIR"

# Файлы предполагается уже распакованы в /opt/bot
if [ ! -f "$INSTALL_DIR/main.py" ]; then
    echo "❌ В $INSTALL_DIR нет main.py. Распакуй сюда архив и запусти снова."
    exit 1
fi

echo "==> Создаю venv и ставлю зависимости…"
cd "$INSTALL_DIR"
python3 -m venv venv
"$INSTALL_DIR/venv/bin/pip" install --upgrade pip
"$INSTALL_DIR/venv/bin/pip" install -r requirements.txt

if [ ! -f "$INSTALL_DIR/.env" ]; then
    echo "==> Копирую .env.example → .env (обязательно отредактируй вручную!)"
    cp .env.example .env
fi

echo "==> systemd-сервис…"
cp deploy/bot.service /etc/systemd/system/bot.service
sed -i "s|/opt/bot|$INSTALL_DIR|g" /etc/systemd/system/bot.service
systemctl daemon-reload
systemctl enable bot

echo ""
echo "✅ Базовая установка завершена."
echo ""
echo "Следующие шаги (вручную):"
echo "  1. nano $INSTALL_DIR/.env   — вписать BOT_TOKEN, ADMIN_IDS, WEBAPP_URL"
echo "  2. cp deploy/nginx.conf /etc/nginx/sites-available/bot"
echo "  3. отредактировать server_name в /etc/nginx/sites-available/bot"
echo "  4. ln -s /etc/nginx/sites-available/bot /etc/nginx/sites-enabled/"
echo "  5. nginx -t && systemctl reload nginx"
echo "  6. certbot --nginx -d yourdomain.com"
echo "  7. systemctl start bot && systemctl status bot"
echo "  8. journalctl -u bot -f  — смотри логи"
