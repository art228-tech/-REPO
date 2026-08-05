"""
Handlers for a single welcome bot instance.
Handles: join requests, /start, user messages, callback queries (button clicks, OP check).
"""
import asyncio
import logging
from aiogram import Router, F, Bot
from aiogram.filters import CommandStart
from aiogram.types import (
    ChatJoinRequest, Message, CallbackQuery
)
from sqlalchemy import select

from shared.db import db
from shared.models import BotUser, ScenarioStep, WelcomeBot, UserStepCompletion
from welcome_bot.utils.scenario_engine import (
    start_scenario, advance_scenario, handle_op_check,
    cancel_reminder
)
from welcome_bot.utils.sender import delete_messages

logger = logging.getLogger(__name__)
router = Router()


@router.chat_join_request()
async def on_join_request(update: ChatJoinRequest, bot: Bot, bot_record: WelcomeBot):
    """User submitted a join request to the channel."""
    user = update.from_user
    ref = getattr(update.invite_link, 'name', None) if update.invite_link else None
    asyncio.create_task(
        start_scenario(bot, bot_record, user.id, user.username, user.full_name, ref)
    )


@router.message(CommandStart())
async def on_start(message: Message, bot: Bot, bot_record: WelcomeBot):
    """User starts the bot directly (e.g. from a deep link)."""
    user = message.from_user
    # Extract ref from deep link param: /start ref_XXXXX
    ref = None
    args = message.text.split(maxsplit=1)
    if len(args) > 1:
        ref = args[1]

    asyncio.create_task(
        start_scenario(bot, bot_record, user.id, user.username, user.full_name, ref)
    )


@router.message()
async def on_user_message(message: Message, bot: Bot, bot_record: WelcomeBot):
    """User sent a text/media message — advance scenario if we're waiting for input."""
    user_id = message.from_user.id

    async with db() as session:
        user = (await session.execute(
            select(BotUser).where(
                BotUser.bot_id == bot_record.id,
                BotUser.user_id == user_id
            )
        )).scalar_one_or_none()

        if not user:
            return

        result = await session.execute(
            select(ScenarioStep)
            .where(
                ScenarioStep.bot_id == bot_record.id,
                ScenarioStep.position == user.current_step
            )
        )
        current_step = result.scalar_one_or_none()

    if not current_step:
        return

    # Only advance if we're at a message step with no buttons (waiting for any user input)
    if current_step.step_type == "message" and not current_step.has_buttons:
        cancel_reminder(bot_record.id, user_id)

        # Mark step complete
        async with db() as session:
            user = (await session.execute(
                select(BotUser).where(BotUser.bot_id == bot_record.id, BotUser.user_id == user_id)
            )).scalar_one_or_none()
            if user:
                completion = UserStepCompletion(bot_user_id=user.id, step_id=current_step.id)
                session.add(completion)

        asyncio.create_task(
            advance_scenario(bot, bot_record, user_id, after_step=current_step)
        )


@router.callback_query(F.data.startswith("check_op:"))
async def on_check_op(callback: CallbackQuery, bot: Bot, bot_record: WelcomeBot):
    """User pressed 'Check subscription' in an OP step."""
    parts = callback.data.split(":")
    cb_bot_id = int(parts[1])
    step_id = int(parts[2])
    user_id = callback.from_user.id

    if cb_bot_id != bot_record.id:
        await callback.answer("❌ Ошибка.", show_alert=True)
        return

    await callback.answer("⏳ Проверяю...")
    success, text = await handle_op_check(bot, bot_record.id, step_id, user_id)

    if not success:
        await callback.answer(text, show_alert=True)


@router.callback_query()
async def on_button_click(callback: CallbackQuery, bot: Bot, bot_record: WelcomeBot):
    """User clicked a button in a scenario message step."""
    user_id = callback.from_user.id

    async with db() as session:
        user = (await session.execute(
            select(BotUser).where(
                BotUser.bot_id == bot_record.id,
                BotUser.user_id == user_id
            )
        )).scalar_one_or_none()

        if not user:
            await callback.answer()
            return

        result = await session.execute(
            select(ScenarioStep).where(
                ScenarioStep.bot_id == bot_record.id,
                ScenarioStep.position == user.current_step
            )
        )
        current_step = result.scalar_one_or_none()

    if not current_step or current_step.step_type != "message" or not current_step.has_buttons:
        await callback.answer()
        return

    cancel_reminder(bot_record.id, user_id)

    # Mark step complete
    async with db() as session:
        user = (await session.execute(
            select(BotUser).where(BotUser.bot_id == bot_record.id, BotUser.user_id == user_id)
        )).scalar_one_or_none()
        if user:
            completion = UserStepCompletion(bot_user_id=user.id, step_id=current_step.id)
            session.add(completion)

    await callback.answer()
    asyncio.create_task(
        advance_scenario(bot, bot_record, user_id, after_step=current_step)
    )
