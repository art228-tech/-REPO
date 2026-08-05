"""
Scenario engine: walks users through steps (message → OP → message...).
Handles delays, reminders, button waiting, message deletion.
"""
import asyncio
import logging
from datetime import datetime, timezone

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from shared.db import db
from shared.models import BotUser, ScenarioStep, Sponsor, UserStepCompletion, WelcomeBot
from welcome_bot.utils.sender import send_stored_message, delete_messages
from welcome_bot.utils.subscription import check_subscription

logger = logging.getLogger(__name__)

# Redis key prefix for per-user reminder tasks
# We use asyncio tasks stored in memory (per process)
_reminder_tasks: dict[str, asyncio.Task] = {}


def _reminder_key(bot_id: int, user_id: int) -> str:
    return f"{bot_id}:{user_id}"


def cancel_reminder(bot_id: int, user_id: int):
    key = _reminder_key(bot_id, user_id)
    task = _reminder_tasks.pop(key, None)
    if task:
        task.cancel()


def schedule_reminder(bot: Bot, bot_record: WelcomeBot, user_id: int, step: ScenarioStep):
    """Schedule a reminder to re-send the current step message if user is stuck."""
    if not bot_record.reminder_seconds or bot_record.reminder_seconds <= 0:
        return
    key = _reminder_key(bot_record.id, user_id)
    cancel_reminder(bot_record.id, user_id)

    async def _remind():
        await asyncio.sleep(bot_record.reminder_seconds)
        try:
            async with db() as session:
                user = await session.execute(
                    select(BotUser).where(
                        BotUser.bot_id == bot_record.id,
                        BotUser.user_id == user_id
                    )
                )
                user = user.scalar_one_or_none()
                if not user or user.current_step != step.position:
                    return
                # Delete old messages
                await delete_messages(bot, user_id, user.sent_message_ids or [])
                user.sent_message_ids = []
                # Re-send step
            await send_step(bot, bot_record, user_id, step)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.warning(f"Reminder error for user {user_id}: {e}")

    task = asyncio.create_task(_remind())
    _reminder_tasks[key] = task


async def send_step(bot: Bot, bot_record: WelcomeBot, user_id: int, step: ScenarioStep):
    """Send the given step to the user and set up appropriate waits."""
    sent_ids = []

    if step.step_type == "message":
        if step.message_data:
            mid = await send_stored_message(bot, user_id, step.message_data)
            if mid:
                sent_ids.append(mid)

        # Track sent IDs
        async with db() as session:
            user = (await session.execute(
                select(BotUser).where(BotUser.bot_id == bot_record.id, BotUser.user_id == user_id)
            )).scalar_one_or_none()
            if user:
                user.sent_message_ids = (user.sent_message_ids or []) + sent_ids
                user.current_step = step.position

        if step.has_buttons:
            # Wait for button click — schedule reminder
            schedule_reminder(bot, bot_record, user_id, step)
        else:
            # No buttons: wait for any user message (handled in message handler)
            # OR if no message_data at all — advance immediately
            if not step.message_data:
                await advance_scenario(bot, bot_record, user_id)
            else:
                # We wait for user to send something
                schedule_reminder(bot, bot_record, user_id, step)

    elif step.step_type == "op":
        await send_op_step(bot, bot_record, user_id, step, sent_ids)


async def send_op_step(bot: Bot, bot_record: WelcomeBot, user_id: int, step: ScenarioStep, sent_ids: list):
    """Build and send the OP (mandatory subscription) message."""
    async with db() as session:
        result = await session.execute(
            select(Sponsor).where(Sponsor.step_id == step.id)
        )
        sponsors = result.scalars().all()

    # Build keyboard with sponsor links + check button
    builder = InlineKeyboardBuilder()
    for sp in sponsors:
        builder.row(InlineKeyboardButton(text=f"📢 {sp.title}", url=sp.url))
    builder.row(InlineKeyboardButton(
        text="✅ Проверить подписку",
        callback_data=f"check_op:{bot_record.id}:{step.id}"
    ))
    kb = builder.as_markup()

    op_text = ""
    if step.message_data:
        # Send message with OP keyboard appended
        content_type = step.message_data.get("content_type", "text")
        text = step.message_data.get("text", "")
        caption = step.message_data.get("caption", "")
        file_id = step.message_data.get("file_id")

        if content_type == "text":
            msg = await bot.send_message(user_id, text or "📢 Подпишитесь на наших спонсоров:", reply_markup=kb, parse_mode="HTML")
        elif content_type == "photo":
            msg = await bot.send_photo(user_id, file_id, caption=caption or "📢 Подпишитесь:", reply_markup=kb, parse_mode="HTML")
        elif content_type == "video":
            msg = await bot.send_video(user_id, file_id, caption=caption or "📢 Подпишитесь:", reply_markup=kb, parse_mode="HTML")
        else:
            # Fallback: send custom text + OP keyboard
            msg = await bot.send_message(user_id, "📢 Подпишитесь на наших спонсоров:", reply_markup=kb, parse_mode="HTML")
        sent_ids.append(msg.message_id)
    else:
        msg = await bot.send_message(user_id, "📢 Подпишитесь на наших спонсоров:", reply_markup=kb, parse_mode="HTML")
        sent_ids.append(msg.message_id)

    async with db() as session:
        user = (await session.execute(
            select(BotUser).where(BotUser.bot_id == bot_record.id, BotUser.user_id == user_id)
        )).scalar_one_or_none()
        if user:
            user.sent_message_ids = (user.sent_message_ids or []) + sent_ids
            user.current_step = step.position

    schedule_reminder(bot, bot_record, user_id, step)


async def advance_scenario(bot: Bot, bot_record: WelcomeBot, user_id: int, after_step: ScenarioStep | None = None):
    """Move user to the next step. If delay_after > 0, send waiting text first."""
    async with db() as session:
        user = (await session.execute(
            select(BotUser).where(BotUser.bot_id == bot_record.id, BotUser.user_id == user_id)
        )).scalar_one_or_none()
        if not user:
            return

        # Determine current step
        result = await session.execute(
            select(ScenarioStep)
            .where(ScenarioStep.bot_id == bot_record.id)
            .order_by(ScenarioStep.position)
        )
        steps = result.scalars().all()

    if not steps:
        return

    current_pos = user.current_step
    current_step = next((s for s in steps if s.position == current_pos), None) if after_step is None else after_step
    next_step = next((s for s in steps if s.position > (current_step.position if current_step else -1)), None)

    if not next_step:
        # Scenario complete
        async with db() as session:
            user = (await session.execute(
                select(BotUser).where(BotUser.bot_id == bot_record.id, BotUser.user_id == user_id)
            )).scalar_one_or_none()
            if user:
                user.completed = True
        return

    # Handle delay_after on current step
    if current_step and current_step.delay_after and current_step.delay_after > 0:
        if current_step.waiting_text:
            await bot.send_message(user_id, current_step.waiting_text, parse_mode="HTML")
        await asyncio.sleep(current_step.delay_after)

    # Delete all previous messages
    async with db() as session:
        user = (await session.execute(
            select(BotUser).where(BotUser.bot_id == bot_record.id, BotUser.user_id == user_id)
        )).scalar_one_or_none()
        if user:
            await delete_messages(bot, user_id, user.sent_message_ids or [])
            user.sent_message_ids = []
            user.current_step = next_step.position

    await send_step(bot, bot_record, user_id, next_step)


async def handle_op_check(bot: Bot, bot_id: int, step_id: int, user_id: int):
    """Called when user presses 'check subscription' button."""
    async with db() as session:
        bot_record = await session.get(WelcomeBot, bot_id)
        step = await session.get(ScenarioStep, step_id)
        result = await session.execute(select(Sponsor).where(Sponsor.step_id == step_id))
        sponsors = result.scalars().all()

    if not bot_record or not step:
        return False, "❌ Ошибка конфигурации."

    # Check all sponsors that have channel_id
    failed_sponsors = []
    for sp in sponsors:
        if sp.channel_id and sp.channel_id != 0:
            subscribed = await check_subscription(bot, user_id, sp.channel_id)
            if not subscribed:
                failed_sponsors.append(sp.title)

    if failed_sponsors:
        names = ", ".join(failed_sponsors)
        return False, f"❌ Вы не подписаны на: <b>{names}</b>\nПодпишитесь и нажмите проверить снова."

    # All passed — mark step complete and advance
    async with db() as session:
        user = (await session.execute(
            select(BotUser).where(BotUser.bot_id == bot_id, BotUser.user_id == user_id)
        )).scalar_one_or_none()
        if user:
            completion = UserStepCompletion(bot_user_id=user.id, step_id=step_id)
            session.add(completion)

    cancel_reminder(bot_id, user_id)
    await advance_scenario(bot, bot_record, user_id, after_step=step)
    return True, "✅"


async def start_scenario(bot: Bot, bot_record: WelcomeBot, user_id: int, username: str | None, full_name: str, ref: str | None = None):
    """Called when a new user joins. Register and start the funnel after delay."""
    async with db() as session:
        # Check if already registered
        existing = (await session.execute(
            select(BotUser).where(BotUser.bot_id == bot_record.id, BotUser.user_id == user_id)
        )).scalar_one_or_none()

        if not existing:
            new_user = BotUser(
                bot_id=bot_record.id,
                user_id=user_id,
                username=username,
                full_name=full_name,
                join_ref=ref,
                current_step=-1,
                sent_message_ids=[]
            )
            session.add(new_user)

    # Wait for configured delay
    if bot_record.delay_seconds and bot_record.delay_seconds > 0:
        await asyncio.sleep(bot_record.delay_seconds)

    async with db() as session:
        result = await session.execute(
            select(ScenarioStep)
            .where(ScenarioStep.bot_id == bot_record.id)
            .order_by(ScenarioStep.position)
        )
        steps = result.scalars().all()

    if not steps:
        return

    first_step = steps[0]
    async with db() as session:
        user = (await session.execute(
            select(BotUser).where(BotUser.bot_id == bot_record.id, BotUser.user_id == user_id)
        )).scalar_one_or_none()
        if user:
            user.current_step = first_step.position

    await send_step(bot, bot_record, user_id, first_step)
