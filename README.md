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

## Notes on secrets

The bot token and admin id are **not** stored in the repository. They are read
at runtime from the environment (or a local, git-ignored `.env` file). When
deploying, provide them through your platform's secret management instead of
hardcoding them.
