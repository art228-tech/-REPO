"""
Only allow configured admins to use the constructor bot.
"""
import os
from typing import Any, Awaitable, Callable
from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, TelegramObject


ADMIN_IDS = set(
    int(x.strip())
    for x in os.getenv("CONSTRUCTOR_ADMIN_IDS", "").split(",")
    if x.strip().isdigit()
)


class AdminMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user_id = None
        if isinstance(event, Message):
            user_id = event.from_user.id if event.from_user else None
        elif isinstance(event, CallbackQuery):
            user_id = event.from_user.id if event.from_user else None

        if user_id not in ADMIN_IDS:
            if isinstance(event, Message):
                await event.answer("⛔ Нет доступа.")
            elif isinstance(event, CallbackQuery):
                await event.answer("⛔ Нет доступа.", show_alert=True)
            return
        return await handler(event, data)
