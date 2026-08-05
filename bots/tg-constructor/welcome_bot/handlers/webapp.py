"""
Handles Telegram WebApp data sent from the roulette mini app.
When user clicks "Claim" in the mini app, bot receives web_app_data update.
"""
import json
import logging
import asyncio

from aiogram import Router, F, Bot
from aiogram.types import Message
from sqlalchemy import select

from shared.db import db
from shared.models import BotUser, ScenarioStep, UserStepCompletion, WelcomeBot
from welcome_bot.utils.scenario_engine import advance_scenario, cancel_reminder

logger = logging.getLogger(__name__)
router = Router()


@router.message(F.web_app_data)
async def on_webapp_data(message: Message, bot: Bot, bot_record: WelcomeBot):
    """User sent data from mini app (clicked Claim button)."""
    try:
        data = json.loads(message.web_app_data.data)
    except Exception:
        return

    if data.get("action") != "claimed":
        return

    user_id = message.from_user.id
    prize = data.get("prize", 5000)

    logger.info(f"User {user_id} claimed {prize} stars from mini app")

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
            select(ScenarioStep).where(
                ScenarioStep.bot_id == bot_record.id,
                ScenarioStep.position == user.current_step
            )
        )
        current_step = result.scalar_one_or_none()

    if not current_step:
        return

    cancel_reminder(bot_record.id, user_id)

    # Mark step complete
    async with db() as session:
        user = (await session.execute(
            select(BotUser).where(
                BotUser.bot_id == bot_record.id,
                BotUser.user_id == user_id
            )
        )).scalar_one_or_none()
        if user:
            completion = UserStepCompletion(
                bot_user_id=user.id,
                step_id=current_step.id
            )
            session.add(completion)

    # Advance to next step
    asyncio.create_task(
        advance_scenario(bot, bot_record, user_id, after_step=current_step)
    )
