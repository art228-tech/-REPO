"""Custom aiogram filters."""

from __future__ import annotations

from aiogram.filters import BaseFilter
from aiogram.types import CallbackQuery, Message

from bot.config import Config


class IsAdmin(BaseFilter):
    """Passes only for updates originating from a configured admin."""

    def __init__(self, config: Config) -> None:
        self.config = config

    async def __call__(self, event: Message | CallbackQuery) -> bool:
        user = event.from_user
        return bool(user and self.config.is_admin(user.id))
