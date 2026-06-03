"""
Точка входа бота-конструктора (версия для друга, без рулетки).
Запускает: главный бот-конструктор + все приветки + мониторинг спонсоров.
"""
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
from bots.manager import get_manager
from handlers import register_all


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
log = logging.getLogger("main")


async def main() -> None:
    # 1) База данных
    await init_db(DB_PATH)
    log.info("База инициализирована: %s", DB_PATH)

    # 2) Приветки
    await get_manager().start_all()

    # 3) Главный бот-конструктор
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    register_all(dp)

    log.info("Стартуем главный бот-конструктор…")
    try:
        from utils.sponsor_monitor import sponsor_monitor_loop
        from config import ADMIN_IDS as _ADMIN_IDS
        asyncio.create_task(sponsor_monitor_loop(bot, _ADMIN_IDS))

        await dp.start_polling(bot, allowed_updates=["message", "callback_query"])
    finally:
        log.info("Останавливаемся…")
        await get_manager().stop_all()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        sys.exit(0)
