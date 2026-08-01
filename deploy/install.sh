#!/usr/bin/env bash
# Установка бота на чистый Ubuntu/Debian через Docker.
#
#   curl -fsSL <raw-url>/deploy/install.sh | bash
# либо: git clone ... && bash deploy/install.sh
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/tgparser}"

say() { printf '\n\033[1m==> %s\033[0m\n' "$1"; }
die() { printf '\033[31mОшибка: %s\033[0m\n' "$1" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "запускать от root или через sudo"

say "Проверяю Docker"
if ! command -v docker >/dev/null 2>&1; then
  say "Docker не найден, ставлю"
  apt-get update -qq
  apt-get install -y -qq ca-certificates curl git
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
    -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -qq
  apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-compose-plugin
fi
docker --version

[[ -d "$APP_DIR" ]] || die "каталог $APP_DIR не найден — сначала склонируйте репозиторий"
cd "$APP_DIR"

if [[ ! -f .env ]]; then
  say "Создаю .env из шаблона"
  cp .env.example .env
  chmod 600 .env

  say "Генерирую ключ шифрования сессий"
  KEY=$(docker run --rm python:3.12-slim sh -c \
    "pip install --quiet cryptography && python -c \
     'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'")
  sed -i "s|^SESSION_ENCRYPTION_KEY=.*|SESSION_ENCRYPTION_KEY=${KEY}|" .env

  cat <<'EOF'

Заполните в .env: BOT_TOKEN, API_ID, API_HASH, OWNER_ID.
  BOT_TOKEN        — у @BotFather
  API_ID/API_HASH  — my.telegram.org → API development tools
  OWNER_ID         — ваш id, узнать у @userinfobot

Файл открыт правами 600. Потом запустите:
  cd /opt/tgparser && docker compose up -d --build

EOF
  exit 0
fi

say "Собираю и запускаю"
mkdir -p data
docker compose up -d --build
docker compose ps

say "Готово. Логи: docker compose logs -f"
