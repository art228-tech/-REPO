"""Добавление новой приветки по токену."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bots.manager import get_manager, validate_token
from database import get_db
from handlers.start import is_admin
from keyboards.constructor_kb import back_to, bots_list, main_menu
from states.fsm import AddBotStates
from utils.helpers import parse_token

router = Router(name="add_bot")


@router.callback_query(F.data == "mybots")
async def cb_mybots(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        await cb.answer("⛔", show_alert=True)
        return
    await state.clear()
    bots = await get_db().list_greeting_bots()
    if not bots:
        await cb.message.edit_text(
            "У тебя пока нет приветок. Добавь первую — нажми кнопку ниже.",
            reply_markup=bots_list([]),
        )
    else:
        await cb.message.edit_text(
            f"<b>🤖 Твои приветки</b> — {len(bots)} шт.",
            reply_markup=bots_list(bots),
        )
    await cb.answer()


@router.callback_query(F.data == "addbot")
async def cb_addbot(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        await cb.answer("⛔", show_alert=True)
        return
    await state.set_state(AddBotStates.waiting_for_token)
    await cb.message.edit_text(
        "<b>➕ Добавление приветки</b>\n\n"
        "Пришли токен бота от @BotFather в формате:\n"
        "<code>1234567890:AAAA-...</code>\n\n"
        "Чтобы получить токен — открой @BotFather, создай нового бота "
        "командой /newbot и скопируй токен.",
        reply_markup=back_to("main", "❌ Отмена"),
    )
    await cb.answer()


@router.message(AddBotStates.waiting_for_token)
async def on_token(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return
    token = parse_token(message.text or "")
    if not token:
        await message.answer(
            "❌ Это не похоже на токен. Пришли его в формате <code>123456:AAAA...</code> "
            "или нажми /start, чтобы выйти.",
        )
        return

    info = await validate_token(token)
    if not info:
        await message.answer(
            "❌ Токен невалиден. Telegram отверг его. "
            "Проверь правильность и пришли ещё раз, либо /start чтобы выйти.",
        )
        return

    db = get_db()
    # Проверяем дубль
    existing = await db.get_greeting_bot_by_tg_id(info["tg_id"])
    if existing:
        await message.answer(
            f"⚠️ Этот бот уже добавлен: @{existing['username']}.",
            reply_markup=main_menu(),
        )
        await state.clear()
        return

    bot_id = await db.add_greeting_bot(
        token=token,
        tg_id=info["tg_id"],
        username=info["username"],
        name=info["name"],
        owner_id=message.from_user.id,
    )

    # Запускаем поллинг
    try:
        await get_manager().start_bot(bot_id, token)
    except Exception as e:
        await message.answer(
            f"⚠️ Бот добавлен в БД, но не удалось запустить: {e}",
            reply_markup=main_menu(),
        )
        await state.clear()
        return

    await message.answer(
        f"✅ Приветка <b>@{info['username']}</b> успешно добавлена и запущена!\n\n"
        f"Теперь:\n"
        f"1) Добавь её в канал админом с правом приглашать пользователей\n"
        f"2) Открой её настройки и собери сценарий\n",
        reply_markup=main_menu(),
    )
    await state.clear()
