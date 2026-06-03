"""Обработчики, доступные всем пользователям."""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from aiogram.utils.markdown import hbold

from bot.config import Config
from bot.storage import UserStorage

router = Router(name="common")

HELP_TEXT = (
    "Доступные команды:\n"
    "/start — регистрация и приветствие\n"
    "/help — показать это сообщение\n"
    "/id — показать ваш Telegram ID\n"
)


async def _remember(message: Message, storage: UserStorage) -> None:
    """Сохраняем отправителя, чтобы админ позже мог сделать рассылку."""
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
    name = message.from_user.full_name if message.from_user else "друг"
    greeting = f"Привет, {hbold(name)}! 👋\n\n{HELP_TEXT}"
    if config.is_admin(message.from_user.id if message.from_user else None):
        greeting += "\nВы администратор. Откройте админ-панель командой /admin."
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
        await message.answer("Не удалось определить ваш ID.")
        return
    await message.answer(f"Ваш Telegram ID: {hbold(str(user.id))}")
