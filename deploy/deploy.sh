#!/usr/bin/env bash
#
# Deploy the bot to a remote server over SSH using Docker Compose.
#
# Prerequisites on the server:
#   - Docker Engine + the Docker Compose plugin installed
#   - SSH access for the user below
#
# Usage:
#   ./deploy/deploy.sh                # uses defaults below
#   SSH_HOST=root@1.2.3.4 ./deploy/deploy.sh
#
set -euo pipefail

# --- Configuration (override via environment) --------------------------------
SSH_HOST="${SSH_HOST:-root@62.60.250.242}"
REMOTE_DIR="${REMOTE_DIR:-/opt/telegram-bot}"

# -----------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

echo ">> Deploying to ${SSH_HOST}:${REMOTE_DIR}"

if [[ ! -f "${PROJECT_ROOT}/.env" ]]; then
    echo "!! ${PROJECT_ROOT}/.env not found."
    echo "   Create it from .env.example and set BOT_TOKEN before deploying."
    exit 1
fi

echo ">> Ensuring remote directory exists"
ssh "${SSH_HOST}" "mkdir -p '${REMOTE_DIR}'"

echo ">> Syncing project files"
rsync -az --delete \
    --exclude '.git' \
    --exclude '.venv' \
    --exclude '__pycache__' \
    --exclude '*.sqlite3' \
    --exclude 'data' \
    "${PROJECT_ROOT}/" "${SSH_HOST}:${REMOTE_DIR}/"

echo ">> Building and (re)starting the container"
ssh "${SSH_HOST}" "cd '${REMOTE_DIR}' && docker compose up -d --build"

echo ">> Recent logs"
ssh "${SSH_HOST}" "cd '${REMOTE_DIR}' && docker compose logs --tail 30 bot" || true

echo ">> Done."
