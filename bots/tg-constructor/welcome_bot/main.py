"""
Welcome Bot Manager.
Loads all active welcome bots from DB and runs them concurrently.
Polls the DB periodically to pick up newly added bots.
"""
import asyncio
import logging
import os
import sys

sys.path.insert(0, "/app")

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from shared.models import create_tables, async_session, WelcomeBot
from sqlalchemy import select

from welcome_bot.handlers.user import router as user_router
from welcome_bot.handlers.webapp import router as webapp_router

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

# Running bot instances: bot_id -> (Bot, Dispatcher, polling_task)
_running: dict[int, tuple[Bot, Dispatcher, asyncio.Task]] = {}


def _make_dispatcher(bot_record: WelcomeBot) -> Dispatcher:
    """Create a dispatcher with bot_record injected into all handlers."""
    dp = Dispatcher(storage=MemoryStorage())
    dp["bot_record"] = bot_record
    dp.include_router(webapp_router)
    dp.include_router(user_router)
    return dp


async def start_bot(bot_record: WelcomeBot):
    if bot_record.id in _running:
        return
    try:
        bot = Bot(
            token=bot_record.token,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML)
        )
        dp = _make_dispatcher(bot_record)

        async def _poll():
            try:
                await dp.start_polling(bot, allowed_updates=["message", "callback_query", "chat_join_request"])
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.error(f"Bot {bot_record.name} polling error: {e}")
            finally:
                await bot.session.close()

        task = asyncio.create_task(_poll())
        _running[bot_record.id] = (bot, dp, task)
        logger.info(f"Started bot: {bot_record.name} (@{bot_record.username})")
    except Exception as e:
        logger.error(f"Failed to start bot {bot_record.name}: {e}")


async def stop_bot(bot_id: int):
    if bot_id not in _running:
        return
    bot, dp, task = _running.pop(bot_id)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    await bot.session.close()
    logger.info(f"Stopped bot id={bot_id}")


async def sync_bots():
    """Sync running bots with DB state."""
    async with async_session() as session:
        result = await session.execute(select(WelcomeBot))
        all_bots = result.scalars().all()

    db_active = {b.id: b for b in all_bots if b.is_active}
    db_ids = set(db_active.keys())
    running_ids = set(_running.keys())

    # Start new
    for bid in db_ids - running_ids:
        await start_bot(db_active[bid])

    # Stop removed/paused
    for bid in running_ids - db_ids:
        await stop_bot(bid)


async def main():
    await create_tables()
    logger.info("Welcome bot manager started. Syncing bots...")

    while True:
        try:
            await sync_bots()
        except Exception as e:
            logger.error(f"Sync error: {e}")
        await asyncio.sleep(10)  # Poll DB every 10 seconds


if __name__ == "__main__":
    asyncio.run(main())
