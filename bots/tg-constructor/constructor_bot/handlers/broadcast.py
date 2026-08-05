"""
Broadcast a message to all users of a welcome bot.
"""
import asyncio
from aiogram import Router, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select

from shared.db import db
from shared.models import BotUser, WelcomeBot
from constructor_bot.keyboards.menus import cancel_kb, back_kb
from welcome_bot.utils.sender import send_stored_message

router = Router()


class BroadcastFSM(StatesGroup):
    waiting_message = State()
    confirm = State()


@router.callback_query(F.data.startswith("broadcast:"))
async def cb_broadcast(callback: CallbackQuery, state: FSMContext):
    bot_id = int(callback.data.split(":")[1])
    await state.update_data(bot_id=bot_id)
    await state.set_state(BroadcastFSM.waiting_message)
    await callback.message.edit_text(
        "📣 <b>Рассылка</b>\n\nОтправьте сообщение для рассылки (текст, фото, видео, стикер и т.д.):",
        reply_markup=cancel_kb(f"bot_menu:{bot_id}")
    )
    await callback.answer()


@router.message(BroadcastFSM.waiting_message)
async def fsm_broadcast_message(message: Message, state: FSMContext):
    from constructor_bot.handlers.scenario_editor import _serialize_message
    msg_data = await _serialize_message(message)
    data = await state.get_data()
    await state.update_data(msg_data=msg_data)
    await state.set_state(BroadcastFSM.confirm)

    async with db() as session:
        total = (await session.execute(
            select(BotUser).where(BotUser.bot_id == data["bot_id"])
        )).scalars().all()

    await message.answer(
        f"📣 Готово к рассылке!\nПолучателей: <b>{len(total)}</b>\n\nОтправить?",
        reply_markup=cancel_kb(f"bot_menu:{data['bot_id']}")
    )
    # Confirm button inline
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Отправить", callback_data="do_broadcast"),
        InlineKeyboardButton(text="❌ Отмена", callback_data=f"bot_menu:{data['bot_id']}")
    )
    await message.answer(
        f"✅ Подтвердите рассылку для <b>{len(total)}</b> пользователей:",
        reply_markup=builder.as_markup()
    )


@router.callback_query(F.data == "do_broadcast", BroadcastFSM.confirm)
async def cb_do_broadcast(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    bot_id = data["bot_id"]
    msg_data = data["msg_data"]
    await state.clear()

    async with db() as session:
        bot_record = await session.get(WelcomeBot, bot_id)
        users = (await session.execute(
            select(BotUser).where(BotUser.bot_id == bot_id)
        )).scalars().all()
        user_ids = [u.user_id for u in users]

    await callback.message.edit_text(f"📣 Начинаю рассылку для {len(user_ids)} пользователей...")
    await callback.answer()

    child_bot = Bot(token=bot_record.token)
    success, failed = 0, 0

    for uid in user_ids:
        try:
            await send_stored_message(child_bot, uid, msg_data)
            success += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)  # ~20 msg/sec to avoid flood

    await child_bot.session.close()
    await callback.message.answer(
        f"✅ Рассылка завершена!\n📤 Отправлено: {success}\n❌ Ошибок: {failed}",
        reply_markup=back_kb(f"bot_menu:{bot_id}")
    )
