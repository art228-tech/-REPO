"""Каналы автопостера — привязаны к конкретному помощнику."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from database import get_db
from handlers.common import is_admin
from keyboards.kb import channels_menu, channel_card, helper_pick_for_channel
from states.fsm import ChannelStates
from utils.manager import get_manager

router = Router()


async def _render_channels(cb: CallbackQuery) -> None:
    db = get_db()
    channels = await db.list_channels()
    helpers = await db.list_helpers()
    h_by_id = {h["id"]: h for h in helpers}
    await cb.message.edit_text(
        f"<b>📢 Каналы</b>\n\nВсего: {len(channels)}",
        reply_markup=channels_menu(channels, h_by_id),
    )


@router.callback_query(F.data == "channels")
async def cb_channels(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        await cb.answer("⛔", show_alert=True)
        return
    await state.clear()
    await _render_channels(cb)
    await cb.answer()


@router.callback_query(F.data == "ch_add")
async def cb_ch_add(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        return
    db = get_db()
    helpers = await db.list_active_helpers()
    if not helpers:
        await cb.answer("Сначала добавь помощника", show_alert=True)
        return
    await cb.message.edit_text(
        "<b>➕ Добавить канал</b>\n\n"
        "Выбери помощника, который будет постить в этот канал "
        "(он должен быть админом этого канала):",
        reply_markup=helper_pick_for_channel(helpers),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("ch_pick_h:"))
async def cb_ch_pick_helper(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        return
    helper_id = int(cb.data.split(":")[1])
    h = await get_db().get_helper(helper_id)
    if not h:
        await cb.answer("Помощник не найден", show_alert=True)
        return
    await state.set_state(ChannelStates.wait_forward)
    await state.update_data(ch_helper_id=helper_id)
    await cb.message.edit_text(
        f"<b>➕ Канал для @{h['username']}</b>\n\n"
        f"1. Убедись что этот помощник — <b>админ канала</b> "
        f"с правом публикации и удаления сообщений.\n"
        f"2. Перешли сюда любое сообщение из этого канала.\n\n"
        f"Жду пересланное сообщение…"
    )
    await cb.answer()


@router.message(ChannelStates.wait_forward)
async def m_ch_forward(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return
    origin = getattr(message, "forward_origin", None)
    chat = None
    if origin is not None:
        chat = getattr(origin, "chat", None)
    if chat is None:
        chat = getattr(message, "forward_from_chat", None)
    if chat is None or chat.type not in ("channel", "supergroup"):
        await message.answer("Это не пересланное сообщение из канала.")
        return
    data = await state.get_data()
    helper_id = data["ch_helper_id"]
    db = get_db()
    helper = await db.get_helper(helper_id)
    if not helper:
        await message.answer("Помощник пропал.")
        await state.clear()
        return

    # проверяем что помощник — админ канала с нужными правами
    manager = get_manager()
    bot = manager.get_helper_bot(helper_id)
    if bot is None:
        await message.answer("Помощник не запущен. Возможно, заморожен.")
        await state.clear()
        return
    try:
        member = await bot.get_chat_member(chat.id, (await bot.me()).id)
    except Exception as e:
        await message.answer(
            f"⚠️ Помощник не видит канал. Убедись что он добавлен в админы.\n\n{e}"
        )
        await state.clear()
        return
    if member.status != "administrator":
        await message.answer(
            "⚠️ Помощник не админ канала. Добавь его админом с правами "
            "<b>публикации</b> и <b>удаления</b> сообщений."
        )
        return
    if getattr(member, "can_post_messages", None) is False:
        await message.answer("⚠️ У помощника нет права на публикацию.")
        return
    if getattr(member, "can_delete_messages", None) is False:
        await message.answer("⚠️ У помощника нет права на удаление сообщений.")
        return

    await db.add_channel(helper_id, chat.id, chat.title or "Канал", chat.username)
    await state.clear()
    await message.answer(
        f"✅ Канал «{chat.title}» привязан к @{helper['username']}."
    )
    # перерисовываем список
    helpers_list = await db.list_helpers()
    h_by_id = {h["id"]: h for h in helpers_list}
    chs = await db.list_channels()
    await message.answer(
        f"<b>📢 Каналы</b>\n\nВсего: {len(chs)}",
        reply_markup=channels_menu(chs, h_by_id),
    )


@router.callback_query(F.data.startswith("ch:"))
async def cb_channel_card(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        return
    ch_id = int(cb.data.split(":")[1])
    db = get_db()
    ch = await db.get_channel(ch_id)
    if not ch:
        await cb.answer("Не найдено", show_alert=True)
        return
    helper = await db.get_helper(ch["helper_id"])
    h_name = (helper["name"] or helper["username"]) if helper else "?"
    uname = f"@{ch['username']}" if ch["username"] else "—"
    await cb.message.edit_text(
        f"<b>📢 {ch['title']}</b>\n\n"
        f"Username: {uname}\n"
        f"chat_id: <code>{ch['chat_id']}</code>\n"
        f"Помощник: <b>{h_name}</b>",
        reply_markup=channel_card(ch_id),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("ch_del:"))
async def cb_ch_del(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        return
    ch_id = int(cb.data.split(":")[1])
    await get_db().delete_channel(ch_id)
    await _render_channels(cb)
    await cb.answer("🗑 Канал удалён")
