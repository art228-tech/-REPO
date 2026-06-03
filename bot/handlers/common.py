"""Handlers available to every user."""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from aiogram.utils.markdown import hbold

from bot.config import Config
from bot.storage import UserStorage

router = Router(name="common")

HELP_TEXT = (
    "Available commands:\n"
    "/start — register and see the welcome message\n"
    "/help — show this help message\n"
    "/id — show your Telegram id\n"
)


async def _remember(message: Message, storage: UserStorage) -> None:
    """Persist the sender so admins can broadcast to them later."""
    user = message.from_user
    if user is None:
        return
    await storage.upsert_user(
        user_id=user.id,
        username=user.username,
        full_name=user.full_name,
    )


@router.message(CommandStart())
async def cmd_start(message: Message, storage: UserStorage, config: Config) -> None:
    await _remember(message, storage)
    name = message.from_user.full_name if message.from_user else "there"
    greeting = f"Hello, {hbold(name)}! 👋\n\n{HELP_TEXT}"
    if config.is_admin(message.from_user.id if message.from_user else None):
        greeting += "\nYou are an admin. Use /admin to open the admin panel."
    await message.answer(greeting)


@router.message(Command("help"))
async def cmd_help(message: Message, storage: UserStorage) -> None:
    await _remember(message, storage)
    await message.answer(HELP_TEXT)


@router.message(Command("id"))
async def cmd_id(message: Message, storage: UserStorage) -> None:
    await _remember(message, storage)
    user = message.from_user
    if user is None:
        await message.answer("Could not determine your id.")
        return
    await message.answer(f"Your Telegram id is: {hbold(str(user.id))}")
