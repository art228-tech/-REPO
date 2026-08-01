"""Сборка и запуск бота."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware, Bot, Dispatcher, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, CallbackQuery, Message, TelegramObject

from tgparser.bot.context import BotContext
from tgparser.bot.handlers import (
    auth_handlers,
    common,
    db_handlers,
    scan_handlers,
    settings_handlers,
)
from tgparser.bot.scan_service import ScanService
from tgparser.config import Settings
from tgparser.crypto import SessionCipher
from tgparser.db.engine import Database
from tgparser.userbot.auth import AuthManager

logger = logging.getLogger(__name__)


class AccessControl(BaseMiddleware):
    """Кого пускать в бота.

    В режиме ``open`` пускаются все: данные пользователей изолированы по
    ``owner_id``, поэтому чужие аккаунты, настройки и записи не пересекаются.
    Режим ``allowlist`` оставлен на случай, если доступ понадобится сузить.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user is None:
            return None
        if not self._settings.is_allowed(user.id):
            logger.info("Отклонён запрос от %s (%s)", user.id, user.username)
            return None
        return await handler(event, data)


fallback = Router(name="fallback")


@fallback.callback_query()
async def unknown_callback(call: CallbackQuery) -> None:
    await call.answer("Кнопка устарела, откройте /menu заново.", show_alert=True)


@fallback.message()
async def unknown_message(message: Message) -> None:
    await message.answer("Не понял. /menu — открыть меню.")


def build_dispatcher(ctx: BotContext) -> Dispatcher:
    dispatcher = Dispatcher(storage=MemoryStorage())
    dispatcher.update.outer_middleware(AccessControl(ctx.app_settings))
    dispatcher["ctx"] = ctx

    dispatcher.include_router(common.router)
    dispatcher.include_router(auth_handlers.router)
    dispatcher.include_router(scan_handlers.router)
    dispatcher.include_router(settings_handlers.router)
    dispatcher.include_router(db_handlers.router)
    dispatcher.include_router(fallback)
    return dispatcher


async def run(app_settings: Settings) -> None:
    missing = app_settings.missing_required()
    if missing:
        raise SystemExit(
            "Не заданы обязательные переменные окружения: "
            + ", ".join(missing)
            + "\nСмотрите .env.example."
        )

    app_settings.ensure_dirs()
    database = Database(app_settings.db_url)
    await database.create_all()
    added = await database.migrate()
    if added:
        logger.info("Схема обновлена: %s", ", ".join(added))

    cipher = SessionCipher(app_settings.session_encryption_key)
    ctx = BotContext(
        app_settings=app_settings,
        db=database,
        cipher=cipher,
        auth=AuthManager(app_settings, cipher, database),
        scan=ScanService(app_settings, cipher, database),
    )

    bot = Bot(
        token=app_settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dispatcher = build_dispatcher(ctx)

    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Начать и открыть меню"),
            BotCommand(command="menu", description="Главное меню"),
            BotCommand(command="login", description="Подключить аккаунт"),
            BotCommand(command="cancel", description="Отменить текущее действие"),
        ]
    )

    me = await bot.get_me()
    access = (
        "открытый"
        if app_settings.access_mode == "open"
        else f"по списку ({len(app_settings.allowed_user_ids)} id)"
    )
    logger.info("Бот @%s запущен, доступ %s", me.username, access)

    try:
        await dispatcher.start_polling(
            bot, allowed_updates=["message", "callback_query"]
        )
    finally:
        await ctx.scan.stop_all()
        await ctx.auth.close_all()
        await database.dispose()
        await bot.session.close()
