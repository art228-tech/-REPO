"""Entry point: ``python -m bot``."""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from bot.config import load_config
from bot.handlers import build_router
from bot.storage import UserStorage

logger = logging.getLogger(__name__)


async def _on_startup(bot: Bot) -> None:
    me = await bot.get_me()
    logger.info("Bot started as @%s (id=%s)", me.username, me.id)


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )

    config = load_config()

    storage = UserStorage(config.db_path)
    await storage.init()

    bot = Bot(
        token=config.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())

    # Dependencies injected into handlers by parameter name.
    dp["config"] = config
    dp["storage"] = storage

    dp.include_router(build_router(config))
    dp.startup.register(_on_startup)

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped.")
