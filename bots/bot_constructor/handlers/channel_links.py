"""Инвайт-ссылки канала: создание ботом + статистика вступлений."""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    ChatMemberUpdated,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from aiogram.exceptions import TelegramBadRequest

from database import get_db
from handlers.start import is_admin

log = logging.getLogger("channel_links")
router = Router()


class ChanLink(StatesGroup):
    wait_channel = State()
    wait_name = State()


def _kb(bot_id: int, links: list) -> InlineKeyboardMarkup:
    rows = []
    for l in links:
        rows.append([InlineKeyboardButton(
            text=f"📊 {l['name']}", callback_data=f"clv:{l['id']}")])
    rows.append([InlineKeyboardButton(text="➕ Создать ссылку", callback_data=f"clnew:{bot_id}")])
    rows.append([InlineKeyboardButton(text="« Назад", callback_data=f"bot:{bot_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ===== Список =====
@router.callback_query(F.data.startswith("chlinks:"))
async def cb_list(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        await cb.answer("⛔", show_alert=True)
        return
    bot_id = int(cb.data.split(":")[1])
    links = await get_db().list_channel_links(bot_id)
    await cb.message.edit_text(
        "<b>📊 Ссылки канала</b>\n\n"
        f"Всего: {len(links)}\n\n"
        "Бот создаёт инвайт-ссылки канала и считает, сколько людей "
        "по каждой вступило. Работает только со ссылками, созданными ботом.\n"
        "<i>Приветка должна быть админом канала с правом «Приглашать через ссылки».</i>",
        reply_markup=_kb(bot_id, links),
    )
    await cb.answer()


# ===== Создание =====
@router.callback_query(F.data.startswith("clnew:"))
async def cb_new(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        return
    bot_id = int(cb.data.split(":")[1])
    await state.set_state(ChanLink.wait_channel)
    await state.update_data(bot_id=bot_id)
    await cb.message.edit_text(
        "Пришли <b>chat_id канала</b> (отрицательное число), "
        "для которого создать инвайт-ссылку.\n\n"
        "Приветка должна быть админом этого канала."
    )
    await cb.answer()


@router.message(ChanLink.wait_channel)
async def m_channel(message: Message, state: FSMContext) -> None:
    try:
        cid = int((message.text or "").strip())
    except ValueError:
        await message.answer("Нужно целое число (chat_id канала).")
        return
    await state.update_data(channel_id=cid)
    await state.set_state(ChanLink.wait_name)
    await message.answer(
        "Пришли <b>название</b> ссылки (для админки — например «Реклама в паблике X»):"
    )


@router.message(ChanLink.wait_name)
async def m_name(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.answer("Нужен текст.")
        return
    data = await state.get_data()
    bot_id = data["bot_id"]
    channel_id = data["channel_id"]
    name = message.text.strip()

    # Создаём инвайт-ссылку через приветку (она админ канала)
    from bots.manager import get_manager
    greeter = get_manager().get_bot_instance(bot_id)
    if greeter is None:
        await message.answer("⚠️ Приветка не активна — запусти её и повтори.")
        await state.clear()
        return
    try:
        invite = await greeter.create_chat_invite_link(
            chat_id=channel_id, name=name[:32],
            creates_join_request=True,
        )
    except TelegramBadRequest as e:
        await message.answer(
            f"⚠️ Не удалось создать ссылку.\n\n{e}\n\n"
            "Проверь: приветка — админ канала с правом «Приглашать через ссылки»."
        )
        await state.clear()
        return
    except Exception as e:
        await message.answer(f"⚠️ Ошибка: {e}")
        await state.clear()
        return

    await get_db().add_channel_link(
        bot_id, channel_id, name, invite.invite_link,
    )
    await state.clear()
    links = await get_db().list_channel_links(bot_id)
    await message.answer(
        f"✅ Ссылка создана:\n{invite.invite_link}\n\n"
        "Раздавай её в рекламе — бот посчитает вступления.",
        reply_markup=_kb(bot_id, links),
    )


# ===== Карточка одной ссылки =====
@router.callback_query(F.data.startswith("clv:"))
async def cb_view(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        return
    link_id = int(cb.data.split(":")[1])
    db = get_db()
    link = await db.get_channel_link(link_id)
    if not link:
        await cb.answer("Не найдено", show_alert=True)
        return
    joined = link["joined_count"]
    requested = link["requested_count"]
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗑 Удалить", callback_data=f"cldel:{link_id}")],
        [InlineKeyboardButton(text="« К списку", callback_data=f"chlinks:{link['bot_id']}")],
    ])
    await cb.message.edit_text(
        f"<b>📊 {link['name']}</b>\n\n"
        f"Ссылка: {link['invite_link']}\n"
        f"Канал: <code>{link['channel_id']}</code>\n\n"
        f"✅ Вступило: <b>{joined}</b>\n"
        f"✋ Подали заявку: <b>{requested}</b>",
        reply_markup=kb,
    )
    await cb.answer()


@router.callback_query(F.data.startswith("cldel:"))
async def cb_del(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        return
    link_id = int(cb.data.split(":")[1])
    db = get_db()
    link = await db.get_channel_link(link_id)
    if not link:
        await cb.answer("Не найдено", show_alert=True)
        return
    bot_id = link["bot_id"]
    await db.delete_channel_link(link_id)
    links = await db.list_channel_links(bot_id)
    await cb.message.edit_text(
        "🗑 Ссылка удалена (из статистики; в самом канале не отзывается).",
        reply_markup=_kb(bot_id, links),
    )
    await cb.answer()
