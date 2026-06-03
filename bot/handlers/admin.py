"""Обработчики только для администраторов: панель, статистика, рассылка.

Этот роутер ограничен админами в :func:`bot.handlers.build_router`, поэтому
обработчики ниже могут считать, что отправитель — администратор.
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

# Telegram допускает примерно 30 сообщений в секунду разным пользователям.
_BROADCAST_CHUNK = 25
_BROADCAST_PAUSE = 1.0


class AdminStates(StatesGroup):
    waiting_for_broadcast = State()


@router.message(Command("admin"))
async def cmd_admin(message: Message) -> None:
    await message.answer("Админ-панель:", reply_markup=admin_panel())


@router.callback_query(F.data == "admin:stats")
async def cb_stats(call: CallbackQuery, storage: UserStorage) -> None:
    total = await storage.count_users()
    await call.message.answer(f"Известных пользователей: {total}")
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
        "Отправьте сообщение для рассылки всем пользователям.",
        reply_markup=cancel_keyboard(),
    )
    await call.answer()


@router.callback_query(F.data == "admin:cancel")
async def cb_cancel(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await call.message.answer("Отменено.")
    await call.answer()


@router.message(Command("broadcast"))
async def cmd_broadcast(message: Message, state: FSMContext) -> None:
    await state.set_state(AdminStates.waiting_for_broadcast)
    await message.answer(
        "Отправьте сообщение для рассылки всем пользователям.",
        reply_markup=cancel_keyboard(),
    )


@router.message(StateFilter(AdminStates.waiting_for_broadcast))
async def do_broadcast(
    message: Message, state: FSMContext, bot: Bot, storage: UserStorage
) -> None:
    await state.clear()

    user_ids = await storage.all_user_ids()
    if not user_ids:
        await message.answer("Пока нет пользователей для рассылки.")
        return

    status = await message.answer(f"Рассылка для {len(user_ids)} пользователей…")

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
                logger.warning("Не удалось доставить рассылку %s: %s", user_id, exc)
        await asyncio.sleep(_BROADCAST_PAUSE)

    await status.edit_text(
        f"Рассылка завершена. Доставлено: {sent}, не доставлено: {failed}."
    )
