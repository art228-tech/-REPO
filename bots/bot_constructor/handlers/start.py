"""Главное меню админ-бота, /start, помощь."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from config import ADMIN_IDS
from keyboards.constructor_kb import main_menu

router = Router(name="start")


HELLO = (
    "<b>👋 Привет!</b>\n\n"
    "Это бот-конструктор привет-ботов.\n\n"
    "🤖 <b>Что умеет:</b>\n"
    "• Управлять несколькими приветками по токенам\n"
    "• Настраивать сценарии: 🎰 рулетка, 📢 ОП, 💬 сообщения\n"
    "• Делать рассылки по всем пользователям\n"
    "• Создавать реф-ссылки и видеть подробную статистику\n\n"
    "Выбери действие 👇"
)

HELP = (
    "<b>📖 Краткое руководство</b>\n\n"
    "<b>1) Добавь приветку</b>\n"
    "Нажми «➕ Добавить приветку» и пришли токен бота от @BotFather.\n\n"
    "<b>2) Подключи к каналу</b>\n"
    "Добавь приветку в канал админом с правом приглашать пользователей. "
    "Включи в канале «Приём заявок» — тогда приветка сможет писать новым пользователям.\n\n"
    "<b>3) Настрой сценарий</b>\n"
    "Открой свою приветку → «📜 Сценарий» → «➕ Добавить шаг». Шаги выполняются по порядку.\n\n"
    "<b>4) Типы шагов</b>\n"
    "• 🎰 <b>Рулетка</b> — текст + кнопка-вебка с красивой рулеткой. Всегда даёт 5000 ⭐.\n"
    "• 📢 <b>ОП</b> — обязательная подписка на каналы-спонсоры с проверкой.\n"
    "• 💬 <b>Сообщение</b> — обычное сообщение с кнопками или копией поста.\n\n"
    "<b>5) Реф-ссылки</b>\n"
    "Создай реф-ссылку, чтобы отслеживать, откуда пришли пользователи.\n\n"
    "<b>6) Рассылки</b>\n"
    "Шли любое сообщение всем живым пользователям приветки.\n\n"
    "<b>⚠️ Важно</b>\n"
    "Для проверки подписки на спонсора приветка должна быть админом в канале/группе спонсора."
)


def is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Доступ запрещён.")
        return
    await state.clear()
    await message.answer(HELLO, reply_markup=main_menu())


@router.callback_query(F.data == "main")
async def cb_main(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        await cb.answer("⛔", show_alert=True)
        return
    await state.clear()
    try:
        await cb.message.edit_text(HELLO, reply_markup=main_menu())
    except Exception:
        await cb.message.answer(HELLO, reply_markup=main_menu())
    await cb.answer()


@router.callback_query(F.data == "help")
async def cb_help(cb: CallbackQuery) -> None:
    if not is_admin(cb.from_user.id):
        await cb.answer("⛔", show_alert=True)
        return
    from keyboards.constructor_kb import back_to
    await cb.message.edit_text(HELP, reply_markup=back_to("main"))
    await cb.answer()
