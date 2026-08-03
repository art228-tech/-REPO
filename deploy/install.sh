#!/usr/bin/env bash
set -euo pipefail

APP_DIR=/opt/tg-mailer
SRC_DIR="$(cd "$(dirname "$0")/.." && pwd)"

mkdir -p "$APP_DIR"
rsync -a --delete \
  --exclude '.git' \
  --exclude 'data' \
  --exclude '.venv' \
  --exclude '.env' \
  --exclude '__pycache__' \
  --exclude '*.pyc' \
  "$SRC_DIR/" "$APP_DIR/"

cd "$APP_DIR"
python3 -m venv .venv
.venv/bin/pip install -U pip wheel
.venv/bin/pip install -r requirements.txt

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created .env — fill BOT_TOKEN / API_ID / API_HASH"
fi

mkdir -p data/sessions data/logs data/exports
cp deploy/tg-mailer.service /etc/systemd/system/tg-mailer.service
systemctl daemon-reload
systemctl enable tg-mailer
systemctl restart tg-mailer
systemctl --no-pager -l status tg-mailer || true
echo "Deployed. Logs: journalctl -u tg-mailer -f"
