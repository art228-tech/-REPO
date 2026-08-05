"""Старт, главное меню."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from config import ADMIN_IDS
from keyboards.kb import main_menu

router = Router()


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


MENU_TEXT = (
    "<b>🤖 Автопостер</b>\n\n"
    "Основной бот только настраивает. Постят боты-помощники.\n\n"
    "🤖 <b>Помощники</b> — добавь по токену\n"
    "📢 <b>Каналы</b> — привязаны к помощнику\n"
    "📋 <b>Задачи</b> — наборы постов\n"
    "▶️ <b>Автопостинг</b> — запуск по кругу\n"
)


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Доступ только для администраторов.")
        return
    await message.answer(MENU_TEXT, reply_markup=main_menu())


@router.callback_query(F.data == "menu")
async def cb_menu(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    if not is_admin(cb.from_user.id):
        await cb.answer("⛔", show_alert=True)
        return
    await cb.message.edit_text(MENU_TEXT, reply_markup=main_menu())
    await cb.answer()
