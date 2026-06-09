"""Точка входа: python -m parser_bot"""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties

from .bot import build_dispatcher
from .config import config
from .crawler import Crawler
from .database import Database
from .userbot import UserBot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
log = logging.getLogger("parser_bot")


async def main() -> None:
    problems = config.validate()
    for p in problems:
        log.warning("Конфиг: %s", p)

    db = Database(config.db_path)
    await db.connect()

    userbot = UserBot(config)

    bot = Bot(
        token=config.bot_token,
        default=DefaultBotProperties(parse_mode="HTML"),
    )

    async def notify(text: str) -> None:
        try:
            await bot.send_message(config.admin_id, text)
        except Exception as e:  # noqa: BLE001
            log.warning("Не удалось отправить уведомление: %s", e)

    crawler = Crawler(config, db, userbot, notify)
    dp = build_dispatcher(config, db, userbot, crawler)

    log.info("Бот запускается...")
    try:
        await dp.start_polling(bot)
    finally:
        await crawler.stop()
        await userbot.logout()
        await db.close()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        log.info("Остановлено.")
