# Telegram Bot

An [aiogram](https://docs.aiogram.dev/) 3.x Telegram bot scaffold with:

- `/start`, `/help`, `/id` commands for everyone
- An admin panel (`/admin`) restricted to configured admin id(s)
- A broadcast feature for admins (`/broadcast` or the panel button)
- SQLite storage of known users (standard-library `sqlite3`)
- Configuration via environment variables / `.env`

## Project layout

```
bot/
├── __main__.py        # entry point (python -m bot)
├── config.py          # env-based configuration
├── storage.py         # SQLite user storage
├── filters.py         # IsAdmin filter
├── keyboards.py       # inline keyboards
└── handlers/
    ├── __init__.py    # router assembly
    ├── common.py      # /start, /help, /id
    └── admin.py       # /admin panel, stats, broadcast
deploy/
├── deploy.sh          # one-command remote deploy over SSH (ssh + tar)
└── telegram-bot.service  # systemd unit
Dockerfile
docker-compose.yml
```

## Setup

1. Create a bot with [@BotFather](https://t.me/BotFather) and copy its token.
2. Find your numeric Telegram id (the bot's `/id` command will tell you once it runs).
3. Copy the example config and fill in real values:

   ```bash
   cp .env.example .env
   # then edit .env
   ```

   `.env` is git-ignored on purpose — **never commit your real bot token.**

4. Install dependencies (a virtual environment is recommended):

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

## Configuration

| Variable     | Required | Default              | Description                                              |
| ------------ | -------- | -------------------- | -------------------------------------------------------- |
| `BOT_TOKEN`  | yes      | —                    | Token from @BotFather.                                   |
| `ADMIN_IDS`  | no       | _(empty)_            | Comma-separated admin user ids, e.g. `111,222`.          |
| `DB_PATH`    | no       | `data/bot.sqlite3`   | Path to the SQLite database file.                        |

## Running

```bash
python -m bot
```

The bot uses long polling, so no public URL or webhook setup is required.

## Deployment

The repo ships with Docker, Docker Compose, a systemd unit, and a deploy
script. The intended target server is `62.60.250.242`.

### Option A — Docker Compose (recommended)

On the server:

```bash
git clone <this-repo> /opt/telegram-bot
cd /opt/telegram-bot
cp .env.example .env      # set BOT_TOKEN (and ADMIN_IDS)
docker compose up -d --build
docker compose logs -f bot
```

The SQLite database is stored in the `bot-data` Docker volume, so it survives
container rebuilds.

### Option B — One-command deploy from your machine

From your local checkout (needs only `ssh` + `tar` locally, and Docker on the
server):

```bash
# uses root@62.60.250.242 by default; key already loaded in ssh-agent
./deploy/deploy.sh

# with an explicit SSH key
SSH_KEY=~/.ssh/id_ed25519 SSH_HOST=root@62.60.250.242 ./deploy/deploy.sh

# with a password (requires `sshpass` installed locally)
SSH_PASSWORD='secret' SSH_HOST=root@62.60.250.242 ./deploy/deploy.sh
```

The script transfers the project to `/opt/telegram-bot` on the server (via
`tar` over SSH) and runs `docker compose up -d --build`. Your local `.env` must
exist (it is copied to the server); it is never committed to git.

### Option C — systemd (no Docker)

```bash
sudo useradd --system --create-home --home-dir /opt/telegram-bot botuser
sudo -u botuser git clone <this-repo> /opt/telegram-bot
cd /opt/telegram-bot
sudo -u botuser python3 -m venv .venv
sudo -u botuser .venv/bin/pip install -r requirements.txt
sudo -u botuser cp .env.example .env   # then edit .env

sudo cp deploy/telegram-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now telegram-bot
sudo journalctl -u telegram-bot -f
```

> Security: deploy your real `BOT_TOKEN` only via the server's `.env` (or your
> platform's secret manager). It must never be committed to the repository.

## Notes on secrets

The bot token and admin id are **not** stored in the repository. They are read
at runtime from the environment (or a local, git-ignored `.env` file). When
deploying, provide them through your platform's secret management instead of
hardcoding them.
