#!/usr/bin/env bash
#
# Deploy the bot to a remote server over SSH using Docker Compose.
#
# Requires only `ssh` and `tar` locally (no rsync). The server needs Docker
# Engine + the Docker Compose plugin, plus `tar`.
#
# Authentication (pick one):
#   - SSH key:      SSH_KEY=/path/to/id_ed25519 ./deploy/deploy.sh
#   - Password:     SSH_PASSWORD=secret ./deploy/deploy.sh   (needs `sshpass`)
#   - Agent/default: just run it if your key is already loaded.
#
# Usage:
#   ./deploy/deploy.sh
#   SSH_HOST=root@62.60.250.242 ./deploy/deploy.sh
#
set -euo pipefail

# --- Configuration (override via environment) --------------------------------
SSH_HOST="${SSH_HOST:-root@62.60.250.242}"
REMOTE_DIR="${REMOTE_DIR:-/opt/telegram-bot}"
SSH_PORT="${SSH_PORT:-22}"
SSH_KEY="${SSH_KEY:-}"
SSH_PASSWORD="${SSH_PASSWORD:-}"

# -----------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

SSH_OPTS=(-p "${SSH_PORT}" -o StrictHostKeyChecking=accept-new)
[[ -n "${SSH_KEY}" ]] && SSH_OPTS+=(-i "${SSH_KEY}")

SSH_PREFIX=()
if [[ -n "${SSH_PASSWORD}" ]]; then
    if ! command -v sshpass >/dev/null 2>&1; then
        echo "!! SSH_PASSWORD is set but 'sshpass' is not installed." >&2
        exit 1
    fi
    SSH_PREFIX=(sshpass -p "${SSH_PASSWORD}")
fi

run_ssh() { "${SSH_PREFIX[@]}" ssh "${SSH_OPTS[@]}" "${SSH_HOST}" "$@"; }

echo ">> Deploying to ${SSH_HOST}:${REMOTE_DIR} (port ${SSH_PORT})"

if [[ ! -f "${PROJECT_ROOT}/.env" ]]; then
    echo "!! ${PROJECT_ROOT}/.env not found." >&2
    echo "   Create it from .env.example and set BOT_TOKEN before deploying." >&2
    exit 1
fi

echo ">> Checking remote prerequisites (docker)"
run_ssh "command -v docker >/dev/null 2>&1 || { echo 'Docker is not installed on the server'; exit 1; }"

echo ">> Ensuring remote directory exists"
run_ssh "mkdir -p '${REMOTE_DIR}'"

echo ">> Transferring project files (tar over ssh)"
tar -C "${PROJECT_ROOT}" \
    --exclude='.git' \
    --exclude='.venv' \
    --exclude='__pycache__' \
    --exclude='*.sqlite3' \
    --exclude='data' \
    -czf - . \
  | run_ssh "tar -C '${REMOTE_DIR}' -xzf -"

echo ">> Building and (re)starting the container"
run_ssh "cd '${REMOTE_DIR}' && (docker compose up -d --build || docker-compose up -d --build)"

echo ">> Recent logs"
run_ssh "cd '${REMOTE_DIR}' && (docker compose logs --tail 30 bot || docker-compose logs --tail 30 bot)" || true

echo ">> Done."
