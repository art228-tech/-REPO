"""
Constructor Bot — manages welcome bots, their scenarios and stats.
"""
import asyncio
import logging
import os
import sys

sys.path.insert(0, "/app")

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.redis import RedisStorage

from shared.models import create_tables
from constructor_bot.handlers import (
    start, bots_list, add_bot, scenario_editor,
    broadcast, statistics, bot_settings, roulette
)
from constructor_bot.middlewares.admin import AdminMiddleware

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)


async def main():
    await create_tables()

    token = os.getenv("CONSTRUCTOR_BOT_TOKEN")
    if not token:
        logger.error("CONSTRUCTOR_BOT_TOKEN is not set!")
        return

    redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")
    storage = RedisStorage.from_url(redis_url)

    bot = Bot(
        token=token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    dp = Dispatcher(storage=storage)

    # Admin-only middleware
    dp.message.middleware(AdminMiddleware())
    dp.callback_query.middleware(AdminMiddleware())

    # Register routers
    dp.include_router(start.router)
    dp.include_router(bots_list.router)
    dp.include_router(add_bot.router)
    dp.include_router(scenario_editor.router)
    dp.include_router(broadcast.router)
    dp.include_router(statistics.router)
    dp.include_router(bot_settings.router)
    dp.include_router(roulette.router)

    logger.info("Constructor bot started")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
