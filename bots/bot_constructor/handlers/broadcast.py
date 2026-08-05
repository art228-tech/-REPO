"""Рассылка по живым юзерам приветки."""
from __future__ import annotations

import asyncio
import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bots.manager import get_manager
from config import BROADCAST_RATE_PER_SECOND
from database import get_db
from handlers.start import is_admin
from keyboards.constructor_kb import back_to, bot_menu, yes_no
from states.fsm import BroadcastStates

router = Router(name="broadcast")
log = logging.getLogger("broadcast")


@router.callback_query(F.data.startswith("bc:"))
async def cb_broadcast_start(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        await cb.answer("⛔", show_alert=True)
        return
    bot_id = int(cb.data.split(":")[1])
    await state.set_state(BroadcastStates.content)
    await state.update_data(bot_id=bot_id)
    await cb.message.edit_text(
        "<b>📣 Рассылка</b>\n\n"
        "Пришли сообщение (текст / фото / стикер / гифка / "
        "видео / переслать пост). Оно будет отправлено всем живым "
        "пользователям этой приветки.\n\n"
        "Премиум-стикеры, форматирование, эмодзи — всё сохранится.",
        reply_markup=back_to(f"bot:{bot_id}", "❌ Отмена"),
    )
    await cb.answer()


@router.message(BroadcastStates.content)
async def m_broadcast_content(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return
    data = await state.get_data()
    bot_id = int(data["bot_id"])
    # Сохраняем (from_chat_id, message_id) для copy_message
    await state.update_data(
        from_chat_id=message.chat.id,
        message_id=message.message_id,
    )
    await state.set_state(BroadcastStates.confirm)

    db = get_db()
    alive_count = len(await db.list_alive_user_tg_ids(bot_id))

    await message.answer(
        f"📨 Сообщение готово. Отправить <b>{alive_count}</b> живым юзерам?",
        reply_markup=yes_no(f"bc_yes:{bot_id}", f"bot:{bot_id}"),
    )


@router.callback_query(F.data.startswith("bc_yes:"))
async def cb_broadcast_yes(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        await cb.answer("⛔", show_alert=True)
        return
    bot_id = int(cb.data.split(":")[1])
    data = await state.get_data()
    from_chat_id = int(data.get("from_chat_id", 0))
    message_id = int(data.get("message_id", 0))
    if not from_chat_id or not message_id:
        await cb.answer("Что-то не так с сообщением. Начни заново.", show_alert=True)
        return

    await state.clear()
    db = get_db()
    bot = get_manager().get_bot(bot_id)
    if not bot:
        await cb.message.edit_text("Приветка сейчас не запущена.")
        await cb.answer()
        return

    user_tg_ids = await db.list_alive_user_tg_ids(bot_id)
    await cb.message.edit_text(
        f"🚀 Рассылка стартовала: {len(user_tg_ids)} получателей.\n"
        f"Я пришлю отчёт когда закончу."
    )
    await cb.answer()

    asyncio.create_task(_run_broadcast(
        admin_chat_id=cb.from_user.id,
        admin_bot=cb.bot,
        bot=bot,
        bot_id=bot_id,
        from_chat_id=from_chat_id,
        message_id=message_id,
        user_tg_ids=user_tg_ids,
    ))


async def _run_broadcast(
    *, admin_chat_id, admin_bot, bot, bot_id, from_chat_id, message_id, user_tg_ids
) -> None:
    db = get_db()
    sent, failed = 0, 0
    delay = 1.0 / BROADCAST_RATE_PER_SECOND
    for tg_id in user_tg_ids:
        try:
            await bot.copy_message(
                chat_id=tg_id,
                from_chat_id=from_chat_id,
                message_id=message_id,
            )
            sent += 1
        except TelegramForbiddenError:
            # юзер заблокировал бота — помечаем мёртвым
            failed += 1
            user = await db.get_user_by_tg(bot_id, tg_id)
            if user:
                await db.mark_user_dead(user["id"])
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after + 1)
            try:
                await bot.copy_message(
                    chat_id=tg_id,
                    from_chat_id=from_chat_id,
                    message_id=message_id,
                )
                sent += 1
            except Exception:
                failed += 1
        except Exception as e:
            failed += 1
            log.warning("broadcast to %s failed: %s", tg_id, e)
        await asyncio.sleep(delay)
    try:
        await admin_bot.send_message(
            admin_chat_id,
            f"✅ Рассылка завершена.\n\n"
            f"📤 Отправлено: <b>{sent}</b>\n"
            f"❌ Не доставлено: <b>{failed}</b>\n"
            f"Заблокировавшие помечены как мёртвые.",
            reply_markup=bot_menu(bot_id),
        )
    except Exception:
        pass
