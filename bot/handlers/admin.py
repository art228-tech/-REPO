"""Admin-only handlers: admin panel, stats and broadcast.

This router is filtered to admins in :func:`bot.handlers.build_router`, so the
handlers here can assume the sender is an admin.
"""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bot.keyboards import admin_panel, cancel_keyboard
from bot.storage import UserStorage, chunked

logger = logging.getLogger(__name__)

router = Router(name="admin")

# Telegram allows roughly 30 messages per second to different users.
_BROADCAST_CHUNK = 25
_BROADCAST_PAUSE = 1.0


class AdminStates(StatesGroup):
    waiting_for_broadcast = State()


@router.message(Command("admin"))
async def cmd_admin(message: Message) -> None:
    await message.answer("Admin panel:", reply_markup=admin_panel())


@router.callback_query(F.data == "admin:stats")
async def cb_stats(call: CallbackQuery, storage: UserStorage) -> None:
    total = await storage.count_users()
    await call.message.answer(f"Known users: {total}")
    await call.answer()


@router.callback_query(F.data == "admin:close")
async def cb_close(call: CallbackQuery) -> None:
    if call.message:
        await call.message.delete()
    await call.answer()


@router.callback_query(F.data == "admin:broadcast")
async def cb_broadcast(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminStates.waiting_for_broadcast)
    await call.message.answer(
        "Send me the message to broadcast to all users.",
        reply_markup=cancel_keyboard(),
    )
    await call.answer()


@router.callback_query(F.data == "admin:cancel")
async def cb_cancel(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await call.message.answer("Cancelled.")
    await call.answer()


@router.message(Command("broadcast"))
async def cmd_broadcast(message: Message, state: FSMContext) -> None:
    await state.set_state(AdminStates.waiting_for_broadcast)
    await message.answer(
        "Send me the message to broadcast to all users.",
        reply_markup=cancel_keyboard(),
    )


@router.message(StateFilter(AdminStates.waiting_for_broadcast))
async def do_broadcast(
    message: Message, state: FSMContext, bot: Bot, storage: UserStorage
) -> None:
    await state.clear()

    user_ids = await storage.all_user_ids()
    if not user_ids:
        await message.answer("There are no users to broadcast to yet.")
        return

    status = await message.answer(f"Broadcasting to {len(user_ids)} users…")

    sent = 0
    failed = 0
    for batch in chunked(user_ids, _BROADCAST_CHUNK):
        for user_id in batch:
            try:
                await message.copy_to(chat_id=user_id)
                sent += 1
            except TelegramRetryAfter as exc:
                await asyncio.sleep(exc.retry_after)
                try:
                    await message.copy_to(chat_id=user_id)
                    sent += 1
                except TelegramAPIError:
                    failed += 1
            except TelegramAPIError as exc:
                failed += 1
                logger.warning("Failed to deliver broadcast to %s: %s", user_id, exc)
        await asyncio.sleep(_BROADCAST_PAUSE)

    await status.edit_text(
        f"Broadcast finished. Delivered: {sent}, failed: {failed}."
    )
