"""Добавление и управление каналами."""
from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from database import get_db
from handlers.common import is_admin
from keyboards.kb import channel_card, channels_menu
from states.fsm import ChannelStates

router = Router()


@router.callback_query(F.data == "channels")
async def cb_channels(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        await cb.answer("⛔", show_alert=True)
        return
    await state.clear()
    channels = await get_db().list_channels()
    await cb.message.edit_text(
        f"<b>📢 Каналы</b>\n\nВсего: {len(channels)}",
        reply_markup=channels_menu(channels),
    )
    await cb.answer()


@router.callback_query(F.data == "ch_add")
async def cb_ch_add(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        return
    await state.set_state(ChannelStates.wait_forward)
    await cb.message.edit_text(
        "<b>➕ Добавить канал</b>\n\n"
        "1. Добавь этого бота в канал <b>администратором</b> "
        "с правами <b>публикации</b> и <b>удаления</b> сообщений.\n"
        "2. Перешли сюда любое сообщение из этого канала.\n\n"
        "Жду пересланное сообщение…"
    )
    await cb.answer()


@router.message(ChannelStates.wait_forward)
async def m_ch_forward(message: Message, state: FSMContext, bot: Bot) -> None:
    if not is_admin(message.from_user.id):
        return
    origin = getattr(message, "forward_origin", None)
    chat = None
    if origin is not None:
        chat = getattr(origin, "chat", None)
    if chat is None:
        chat = getattr(message, "forward_from_chat", None)

    if chat is None or chat.type not in ("channel", "supergroup"):
        await message.answer(
            "Это не пересланное сообщение из канала. "
            "Перешли пост именно из канала."
        )
        return

    # проверяем, что бот — админ с правом постинга
    try:
        member = await bot.get_chat_member(chat.id, (await bot.me()).id)
    except Exception as e:
        await message.answer(
            f"⚠️ Не вижу канал. Убедись, что бот добавлен в него админом.\n\n{e}"
        )
        await state.clear()
        return

    can_post = getattr(member, "can_post_messages", None)
    if member.status != "administrator" or can_post is False:
        await message.answer(
            "⚠️ Бот должен быть <b>администратором</b> канала с правом "
            "<b>публикации сообщений</b>. Проверь права и перешли пост заново."
        )
        return

    await get_db().add_channel(chat.id, chat.title or "Канал", chat.username)
    await state.clear()
    channels = await get_db().list_channels()
    await message.answer(
        f"✅ Канал «{chat.title}» добавлен.",
        reply_markup=channels_menu(channels),
    )


@router.callback_query(F.data.startswith("ch:"))
async def cb_channel_card(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        return
    ch_id = int(cb.data.split(":")[1])
    ch = await get_db().get_channel(ch_id)
    if not ch:
        await cb.answer("Не найдено", show_alert=True)
        return
    uname = f"@{ch['username']}" if ch["username"] else "—"
    await cb.message.edit_text(
        f"<b>📢 {ch['title']}</b>\n\n"
        f"Username: {uname}\n"
        f"chat_id: <code>{ch['chat_id']}</code>",
        reply_markup=channel_card(ch_id),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("ch_del:"))
async def cb_channel_del(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        return
    ch_id = int(cb.data.split(":")[1])
    await get_db().delete_channel(ch_id)
    channels = await get_db().list_channels()
    await cb.message.edit_text(
        "🗑 Канал удалён.", reply_markup=channels_menu(channels)
    )
    await cb.answer()
