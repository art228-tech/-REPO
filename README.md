# Bot configuration

This repository expects bot credentials to be provided through environment
variables, not committed to Git.

## Local setup

1. Copy the example environment file:

   ```bash
   cp .env.example .env
   ```

2. Edit `.env` and set:

   - `TELEGRAM_BOT_TOKEN` to your Telegram bot token
   - `ADMIN_ID` to the Telegram user ID that should have admin access

The `.env` file is ignored by Git so real credentials stay local.