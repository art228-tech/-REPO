"""
Add a new welcome bot by its token.
"""
from aiogram import Router, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.exceptions import TelegramUnauthorizedError

from shared.db import db
from shared.models import WelcomeBot
from constructor_bot.keyboards.menus import cancel_kb, bot_menu_kb

router = Router()


class AddBotFSM(StatesGroup):
    waiting_token = State()
    waiting_delay = State()
    waiting_reminder = State()


@router.callback_query(F.data == "add_bot")
async def cb_add_bot(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AddBotFSM.waiting_token)
    await callback.message.edit_text(
        "🤖 <b>Добавление нового приветственного бота</b>\n\n"
        "Отправьте токен бота (получите у @BotFather):\n\n"
        "<i>Пример: 1234567890:AAHxxxx...</i>",
        reply_markup=cancel_kb("bots_list")
    )
    await callback.answer()


@router.message(AddBotFSM.waiting_token)
async def fsm_got_token(message: Message, state: FSMContext):
    token = message.text.strip()

    # Validate token by calling getMe
    try:
        test_bot = Bot(token=token)
        me = await test_bot.get_me()
        await test_bot.session.close()
    except TelegramUnauthorizedError:
        await message.answer(
            "❌ Неверный токен. Попробуйте ещё раз:",
            reply_markup=cancel_kb("bots_list")
        )
        return
    except Exception as e:
        await message.answer(
            f"❌ Ошибка: {e}\nПопробуйте ещё раз:",
            reply_markup=cancel_kb("bots_list")
        )
        return

    # Check if token already added
    from sqlalchemy import select
    async with db() as session:
        exists = (await session.execute(
            select(WelcomeBot).where(WelcomeBot.token == token)
        )).scalar_one_or_none()

    if exists:
        await message.answer(
            "⚠️ Этот бот уже добавлен!",
            reply_markup=cancel_kb("bots_list")
        )
        await state.clear()
        return

    await state.update_data(token=token, bot_username=me.username, bot_name=me.full_name)
    await state.set_state(AddBotFSM.waiting_delay)
    await message.answer(
        f"✅ Бот <b>@{me.username}</b> найден!\n\n"
        f"⏱ Через сколько <b>секунд</b> после подачи заявки бот впервые напишет пользователю?\n"
        f"<i>(Введите число, например 60. По умолчанию — 0)</i>",
        reply_markup=cancel_kb("bots_list")
    )


@router.message(AddBotFSM.waiting_delay)
async def fsm_got_delay(message: Message, state: FSMContext):
    text = message.text.strip()
    if not text.isdigit():
        await message.answer("❌ Введите число (секунды):")
        return

    await state.update_data(delay_seconds=int(text))
    await state.set_state(AddBotFSM.waiting_reminder)
    await message.answer(
        "🔔 Через сколько секунд <b>дублировать сообщение</b>, если пользователь завис на шаге?\n"
        "<i>(Введите число, например 3600. По умолчанию — 3600)</i>",
        reply_markup=cancel_kb("bots_list")
    )


@router.message(AddBotFSM.waiting_reminder)
async def fsm_got_reminder(message: Message, state: FSMContext):
    text = message.text.strip()
    if not text.isdigit():
        await message.answer("❌ Введите число (секунды):")
        return

    data = await state.get_data()
    await state.clear()

    async with db() as session:
        new_bot = WelcomeBot(
            token=data["token"],
            username=data["bot_username"],
            name=data["bot_name"],
            delay_seconds=data["delay_seconds"],
            reminder_seconds=int(text),
        )
        session.add(new_bot)
        await session.flush()
        bot_id = new_bot.id

    await message.answer(
        f"✅ Бот <b>@{data['bot_username']}</b> успешно добавлен!\n\n"
        f"Теперь настройте сценарий — добавьте шаги (сообщения, ОП).",
        reply_markup=bot_menu_kb(bot_id)
    )
