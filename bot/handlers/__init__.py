"""Routers that make up the bot's behaviour."""

from __future__ import annotations

from aiogram import Router

from bot.config import Config
from bot.filters import IsAdmin

from . import admin, common


def build_router(config: Config) -> Router:
    """Combine all feature routers into a single root router."""
    # Restrict the admin router to configured admins for both messages and
    # callback queries.
    admin.router.message.filter(IsAdmin(config))
    admin.router.callback_query.filter(IsAdmin(config))

    root = Router(name="root")
    # Admin router first so admin-only commands take precedence.
    root.include_router(admin.router)
    root.include_router(common.router)
    return root


__all__ = ["build_router"]
