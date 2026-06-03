"""
Точка входа бота-конструктора.

Запускает:
- Главный бот-конструктор (polling)
- Все приветки (polling) — через BotManager
- Веб-сервер для рулетки (aiohttp)
"""
from __future__ import annotations

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from config import BOT_TOKEN, DB_PATH, WEBAPP_HOST, WEBAPP_PORT, WEBAPP_URL
from database import init_db
from bots.manager import get_manager
from handlers import register_all
from webapp.server import start_webapp


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
log = logging.getLogger("main")


async def main() -> None:
    # 1) База данных
    await init_db(DB_PATH)
    log.info("База инициализирована: %s", DB_PATH)

    # 2) Веб-сервер для рулетки
    runner, site = await start_webapp(WEBAPP_HOST, WEBAPP_PORT)
    if WEBAPP_URL:
        log.info("Публичный URL рулетки: %s/roulette", WEBAPP_URL)
    else:
        log.warning(
            "ВНИМАНИЕ: WEBAPP_URL не задан в .env. "
            "Рулетка не сможет открыться (нужен HTTPS-домен)."
        )

    # 3) Приветки
    await get_manager().start_all()

    # 4) Главный бот-конструктор
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    register_all(dp)

    log.info("Стартуем главный бот-конструктор…")
    try:
        await dp.start_polling(bot, allowed_updates=["message", "callback_query"])
    finally:
        log.info("Останавливаемся…")
        await get_manager().stop_all()
        try:
            await runner.cleanup()
        except Exception:
            pass
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        sys.exit(0)
