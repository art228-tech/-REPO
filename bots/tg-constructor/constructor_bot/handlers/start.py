"""
/start and main menu.
"""
from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery

from constructor_bot.keyboards.menus import main_menu_kb

router = Router()

WELCOME_TEXT = (
    "👋 <b>Конструктор приветственных ботов</b>\n\n"
    "Здесь вы можете:\n"
    "• Добавить нового приветственного бота по токену\n"
    "• Настроить сценарий: сообщения, ОП, задержки\n"
    "• Смотреть статистику и делать рассылки\n\n"
    "Выберите действие:"
)


@router.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(WELCOME_TEXT, reply_markup=main_menu_kb())


@router.callback_query(F.data == "main_menu")
async def cb_main_menu(callback: CallbackQuery):
    await callback.message.edit_text(WELCOME_TEXT, reply_markup=main_menu_kb())
    await callback.answer()
