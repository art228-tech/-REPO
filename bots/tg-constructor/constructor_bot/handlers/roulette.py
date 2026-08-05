"""
Add roulette mini app as a step in the scenario.
Creates a message with a WebApp button that opens the roulette.
"""
from aiogram import Router, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from shared.db import db
from shared.models import ScenarioStep, WelcomeBot
from constructor_bot.keyboards.menus import cancel_kb
from sqlalchemy import select

router = Router()

MINIAPP_URL = ""  # Заполняется из .env


class RouletteFSM(StatesGroup):
    waiting_text = State()
    waiting_url = State()


@router.callback_query(F.data.startswith("add_roulette:"))
async def cb_add_roulette(callback: CallbackQuery, state: FSMContext):
    bot_id = int(callback.data.split(":")[1])
    await state.update_data(bot_id=bot_id)
    await state.set_state(RouletteFSM.waiting_url)
    await callback.message.edit_text(
        "🎰 <b>Добавление рулетки</b>\n\n"
        "Введите URL мини-аппа (где хостится roulette.html):\n\n"
        "<i>Пример: https://yourdomain.com/roulette</i>\n\n"
        "💡 Мини-апп должен быть доступен по HTTPS.\n"
        "Можно использовать ngrok для теста или любой хостинг.",
        reply_markup=cancel_kb(f"scenario:{bot_id}")
    )
    await callback.answer()


@router.message(RouletteFSM.waiting_url)
async def fsm_roulette_url(message: Message, state: FSMContext):
    url = message.text.strip()
    if not url.startswith("https://"):
        await message.answer(
            "❌ URL должен начинаться с <b>https://</b>\n"
            "Telegram требует HTTPS для мини-аппов.\n\nВведите снова:"
        )
        return

    await state.update_data(miniapp_url=url)
    await state.set_state(RouletteFSM.waiting_text)
    await message.answer(
        "✏️ Введите текст сообщения, которое увидит пользователь перед рулеткой:\n\n"
        "<i>Пример: 🎰 Крути рулетку и забирай свой приз!</i>"
    )


@router.message(RouletteFSM.waiting_text)
async def fsm_roulette_text(message: Message, state: FSMContext):
    data = await state.get_data()
    bot_id = data["bot_id"]
    url = data["miniapp_url"]
    text = message.html_text

    # Determine next position
    async with db() as session:
        result = await session.execute(
            select(ScenarioStep)
            .where(ScenarioStep.bot_id == bot_id)
            .order_by(ScenarioStep.position.desc())
        )
        last = result.scalars().first()
        position = (last.position + 1) if last else 0

        # Create step with WebApp button
        msg_data = {
            "content_type": "text",
            "text": text,
            "buttons": [[{
                "text": "🎰 Крутить рулетку",
                "web_app": url
            }]]
        }

        new_step = ScenarioStep(
            bot_id=bot_id,
            step_type="message",
            position=position,
            message_data=msg_data,
            has_buttons=True  # wait for web_app_data
        )
        session.add(new_step)
        await session.flush()
        step_id = new_step.id

    await state.clear()

    from constructor_bot.keyboards.menus import step_menu_kb
    await message.answer(
        f"✅ Шаг с рулеткой добавлен!\n\n"
        f"🎰 Текст: {text[:50]}...\n"
        f"🔗 URL: {url}\n\n"
        f"Пользователь увидит кнопку <b>«Крутить рулетку»</b>, "
        f"откроет мини-апп, и после нажатия «Забрать» — сценарий продолжится.",
        reply_markup=step_menu_kb(step_id, bot_id, "message")
    )
