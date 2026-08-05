"""Каналы автоприёма — привязка к помощнику + настройки автоприёма."""
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
        f"<b>📢 Каналы</b>\n\nВсего: {len(channels)}\n"
        "🟢 — автоприём вкл, ⚪ — выкл",
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
    helpers = await get_db().list_active_helpers()
    if not helpers:
        await cb.answer("Сначала добавь помощника", show_alert=True)
        return
    await cb.message.edit_text(
        "<b>➕ Добавить канал</b>\n\nКакой помощник будет принимать "
        "заявки в этом канале? Он должен быть там админом с правом "
        "«Добавлять участников».",
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
        "1. Убедись что помощник — <b>админ канала</b> с правом "
        "«Добавлять участников».\n"
        "2. Перешли сюда любое сообщение из этого канала.\n\n"
        "Жду пересланное сообщение…"
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

    bot = get_manager().get_helper_bot(helper_id)
    if bot is None:
        await message.answer("Помощник не запущен. Возможно, заморожен.")
        await state.clear()
        return

    # проверка: помощник админ с правом приглашать
    try:
        member = await bot.get_chat_member(chat.id, (await bot.me()).id)
    except Exception as e:
        await message.answer(
            f"⚠️ Помощник не видит канал. Добавь его админом.\n\n{e}"
        )
        await state.clear()
        return
    if member.status != "administrator":
        await message.answer(
            "⚠️ Помощник не админ канала. Дай ему права админа "
            "с разрешением «Добавлять участников»."
        )
        return
    if getattr(member, "can_invite_users", None) is False:
        await message.answer(
            "⚠️ У помощника нет права «Добавлять участников» — без него "
            "одобрять заявки нельзя."
        )
        return

    await db.add_channel(helper_id, chat.id, chat.title or "Канал", chat.username)
    await state.clear()
    await message.answer(
        f"✅ Канал «{chat.title}» привязан к @{helper['username']}.\n"
        "По умолчанию: автоприём ВКЛ, задержка 0 с. Настрой в карточке канала."
    )
    # перерисуем список
    chs = await db.list_channels()
    helpers_list = await db.list_helpers()
    h_by_id = {h["id"]: h for h in helpers_list}
    await message.answer(
        f"<b>📢 Каналы</b>\n\nВсего: {len(chs)}",
        reply_markup=channels_menu(chs, h_by_id),
    )


async def _render_channel_card(cb_or_msg, ch_id: int) -> None:
    db = get_db()
    ch = await db.get_channel(ch_id)
    if not ch:
        return
    helper = await db.get_helper(ch["helper_id"])
    h_name = (helper["name"] or helper["username"]) if helper else "?"
    h_status = " 💀" if helper and not helper["is_alive"] else ""
    queued = await db.count_pending_accepts(ch_id)
    uname = f"@{ch['username']}" if ch["username"] else "—"
    txt = (
        f"<b>📢 {ch['title']}</b>\n\n"
        f"Username: {uname}\n"
        f"chat_id: <code>{ch['chat_id']}</code>\n"
        f"Помощник: <b>{h_name}</b>{h_status}\n"
        f"В очереди приёма: <b>{queued}</b>"
    )
    if hasattr(cb_or_msg, "message"):
        await cb_or_msg.message.edit_text(txt, reply_markup=channel_card(ch))
    else:
        await cb_or_msg.answer(txt, reply_markup=channel_card(ch))


@router.callback_query(F.data.startswith("ch:"))
async def cb_ch_card(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        return
    ch_id = int(cb.data.split(":")[1])
    await _render_channel_card(cb, ch_id)
    await cb.answer()


@router.callback_query(F.data.startswith("ch_toggle:"))
async def cb_ch_toggle(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        return
    ch_id = int(cb.data.split(":")[1])
    ch = await get_db().get_channel(ch_id)
    new_on = 0 if ch["auto_accept"] else 1
    await get_db().set_channel_auto_accept(ch_id, new_on)
    await _render_channel_card(cb, ch_id)
    await cb.answer("Автоприём " + ("включён" if new_on else "выключен"))


@router.callback_query(F.data.startswith("ch_delay:"))
async def cb_ch_delay(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        return
    ch_id = int(cb.data.split(":")[1])
    await state.set_state(ChannelStates.wait_delay)
    await state.update_data(ch_delay_id=ch_id)
    await cb.message.edit_text(
        "⏱ Пришли <b>задержку приёма</b> в секундах (0 — сразу).\n\n"
        "Примеры: <code>0</code>, <code>60</code>, <code>3600</code> (час), "
        "<code>86400</code> (сутки)."
    )
    await cb.answer()


@router.message(ChannelStates.wait_delay)
async def m_ch_delay(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return
    try:
        v = int((message.text or "").strip())
        if v < 0:
            raise ValueError
    except ValueError:
        await message.answer("Нужно целое число секунд (0 или больше).")
        return
    data = await state.get_data()
    ch_id = data["ch_delay_id"]
    await get_db().set_channel_delay(ch_id, v)
    await state.clear()
    await message.answer(f"✅ Задержка установлена: {v} с.")
    await _render_channel_card(message, ch_id)


@router.callback_query(F.data.startswith("ch_del:"))
async def cb_ch_del(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        return
    ch_id = int(cb.data.split(":")[1])
    await get_db().delete_channel(ch_id)
    await _render_channels(cb)
    await cb.answer("🗑 Канал удалён")
