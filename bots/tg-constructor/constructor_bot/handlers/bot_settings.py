"""
Bot settings: delay, reminder, channel binding.
"""
from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from shared.db import db
from shared.models import WelcomeBot
from constructor_bot.keyboards.menus import cancel_kb, back_kb

router = Router()


class BotSettingsFSM(StatesGroup):
    waiting_delay = State()
    waiting_reminder = State()
    waiting_channel_id = State()


@router.callback_query(F.data.startswith("bot_settings:"))
async def cb_bot_settings(callback: CallbackQuery):
    bot_id = int(callback.data.split(":")[1])
    async with db() as session:
        bot = await session.get(WelcomeBot, bot_id)

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="⏱ Задержка первого сообщения", callback_data=f"set_bot_delay:{bot_id}"))
    builder.row(InlineKeyboardButton(text="🔔 Таймер напоминания", callback_data=f"set_bot_reminder:{bot_id}"))
    builder.row(InlineKeyboardButton(text="📡 Привязать канал", callback_data=f"set_bot_channel:{bot_id}"))
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data=f"bot_menu:{bot_id}"))

    text = (
        f"⚙️ <b>Настройки: {bot.name}</b>\n\n"
        f"⏱ Задержка первого сообщения: <b>{bot.delay_seconds} сек</b>\n"
        f"🔔 Напоминание при зависании: <b>{bot.reminder_seconds} сек</b>\n"
        f"📡 Канал: <b>{bot.channel_title or 'не привязан'}</b>"
    )
    await callback.message.edit_text(text, reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data.startswith("set_bot_delay:"))
async def cb_set_bot_delay(callback: CallbackQuery, state: FSMContext):
    bot_id = int(callback.data.split(":")[1])
    await state.update_data(bot_id=bot_id)
    await state.set_state(BotSettingsFSM.waiting_delay)
    await callback.message.edit_text(
        "⏱ Введите задержку в секундах перед первым сообщением (0 = сразу):",
        reply_markup=cancel_kb(f"bot_settings:{bot_id}")
    )
    await callback.answer()


@router.message(BotSettingsFSM.waiting_delay)
async def fsm_bot_delay(message: Message, state: FSMContext):
    if not message.text.strip().isdigit():
        await message.answer("❌ Введите число:")
        return
    data = await state.get_data()
    async with db() as session:
        bot = await session.get(WelcomeBot, data["bot_id"])
        bot.delay_seconds = int(message.text.strip())
    await state.clear()
    await message.answer("✅ Задержка обновлена!", reply_markup=back_kb(f"bot_settings:{data['bot_id']}"))


@router.callback_query(F.data.startswith("set_bot_reminder:"))
async def cb_set_bot_reminder(callback: CallbackQuery, state: FSMContext):
    bot_id = int(callback.data.split(":")[1])
    await state.update_data(bot_id=bot_id)
    await state.set_state(BotSettingsFSM.waiting_reminder)
    await callback.message.edit_text(
        "🔔 Через сколько секунд дублировать сообщение если пользователь завис?\n(0 = отключить)",
        reply_markup=cancel_kb(f"bot_settings:{bot_id}")
    )
    await callback.answer()


@router.message(BotSettingsFSM.waiting_reminder)
async def fsm_bot_reminder(message: Message, state: FSMContext):
    if not message.text.strip().isdigit():
        await message.answer("❌ Введите число:")
        return
    data = await state.get_data()
    async with db() as session:
        bot = await session.get(WelcomeBot, data["bot_id"])
        bot.reminder_seconds = int(message.text.strip())
    await state.clear()
    await message.answer("✅ Таймер обновлён!", reply_markup=back_kb(f"bot_settings:{data['bot_id']}"))


@router.callback_query(F.data.startswith("set_bot_channel:"))
async def cb_set_bot_channel(callback: CallbackQuery, state: FSMContext):
    bot_id = int(callback.data.split(":")[1])
    await state.update_data(bot_id=bot_id)
    await state.set_state(BotSettingsFSM.waiting_channel_id)
    await callback.message.edit_text(
        "📡 Введите ID канала, заявки из которого будет обрабатывать этот бот:\n"
        "<i>Пример: -1001234567890</i>\n\n"
        "Бот должен быть добавлен в канал как администратор.",
        reply_markup=cancel_kb(f"bot_settings:{bot_id}")
    )
    await callback.answer()


@router.message(BotSettingsFSM.waiting_channel_id)
async def fsm_bot_channel(message: Message, state: FSMContext):
    text = message.text.strip()
    try:
        channel_id = int(text)
    except ValueError:
        await message.answer("❌ Введите числовой ID:")
        return
    data = await state.get_data()
    # Try to get channel info
    from aiogram import Bot as ABot
    from shared.models import WelcomeBot as WB
    async with db() as session:
        bot_record = await session.get(WB, data["bot_id"])
    try:
        test_bot = ABot(token=bot_record.token)
        chat = await test_bot.get_chat(channel_id)
        await test_bot.session.close()
        title = chat.title
    except Exception:
        title = str(channel_id)
    async with db() as session:
        bot = await session.get(WelcomeBot, data["bot_id"])
        bot.channel_id = channel_id
        bot.channel_title = title
    await state.clear()
    await message.answer(f"✅ Канал <b>{title}</b> привязан!", reply_markup=back_kb(f"bot_settings:{data['bot_id']}"))
