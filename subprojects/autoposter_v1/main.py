"""Точка входа автопостера."""
from __future__ import annotations

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from config import BOT_TOKEN, DB_PATH
from database import init_db
from handlers import register_all
from utils.poster import get_poster

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
log = logging.getLogger("main")


async def main() -> None:
    await init_db(DB_PATH)
    log.info("База инициализирована: %s", DB_PATH)

    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    register_all(dp)

    # Движок автопостинга — фоновый цикл. Состояние в БД,
    # поэтому после перезапуска постинг продолжится сам.
    get_poster().start(bot)

    log.info("Автопостер запускается…")
    try:
        await dp.start_polling(bot, allowed_updates=["message", "callback_query"])
    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        sys.exit(0)
