"""Создание и просмотр реф-ссылок для приветки."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from database import get_db
from handlers.start import is_admin
from keyboards.constructor_kb import back_to, bot_menu
from states.fsm import RefStates

router = Router(name="refs")


def _refs_kb(bot_id: int, refs: list) -> InlineKeyboardMarkup:
    rows = []
    for r in refs:
        rows.append([InlineKeyboardButton(
            text=f"🔗 {r['name'] or r['code']} ({r['code']})",
            callback_data=f"ref_view:{r['id']}",
        )])
    rows.append([InlineKeyboardButton(text="➕ Создать", callback_data=f"ref_new:{bot_id}")])
    rows.append([InlineKeyboardButton(text="« Назад", callback_data=f"bot:{bot_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data.startswith("refs:"))
async def cb_refs(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        await cb.answer("⛔", show_alert=True)
        return
    await state.clear()
    bot_id = int(cb.data.split(":")[1])
    refs = await get_db().list_ref_links(bot_id)
    await cb.message.edit_text(
        f"<b>🔗 Реф-ссылки</b>\nВсего: {len(refs)}\n\n"
        f"Реф-ссылки позволяют отслеживать, откуда пришли юзеры. "
        f"Создай ссылку, дай ей название — и приведи на неё трафик.",
        reply_markup=_refs_kb(bot_id, refs),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("ref_new:"))
async def cb_ref_new(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        await cb.answer("⛔", show_alert=True)
        return
    bot_id = int(cb.data.split(":")[1])
    await state.set_state(RefStates.name)
    await state.update_data(bot_id=bot_id)
    await cb.message.edit_text(
        "Пришли <b>название</b> новой реф-ссылки (для админки, "
        "например <code>TG канал X</code> или <code>Реклама</code>).",
        reply_markup=back_to(f"refs:{bot_id}", "❌ Отмена"),
    )
    await cb.answer()


@router.message(RefStates.name)
async def m_ref_name(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return
    name = (message.text or "").strip()
    if not name:
        await message.answer("Пришли название.")
        return
    data = await state.get_data()
    bot_id = int(data["bot_id"])
    ref = await get_db().add_ref_link(bot_id, name)
    bot_record = await get_db().get_greeting_bot(bot_id)
    await state.clear()
    link = f"https://t.me/{bot_record['username']}?start=ref_{ref['code']}"
    refs = await get_db().list_ref_links(bot_id)
    await message.answer(
        f"✅ Реф-ссылка создана!\n\n"
        f"<b>Название:</b> {name}\n"
        f"<b>Код:</b> <code>{ref['code']}</code>\n"
        f"<b>Ссылка:</b> {link}",
        reply_markup=_refs_kb(bot_id, refs),
    )


@router.callback_query(F.data.startswith("ref_view:"))
async def cb_ref_view(cb: CallbackQuery) -> None:
    if not is_admin(cb.from_user.id):
        await cb.answer("⛔", show_alert=True)
        return
    ref_id = int(cb.data.split(":")[1])
    db = get_db()
    ref = await db.get_ref_link(ref_id)
    if not ref:
        await cb.answer("Не найдено", show_alert=True)
        return
    bot_record = await db.get_greeting_bot(ref["bot_id"])
    link = f"https://t.me/{bot_record['username']}?start=ref_{ref['code']}"
    # Статистика
    cur = await db.conn.execute(
        "SELECT COUNT(*) FROM bot_users WHERE ref_link_id = ?", (ref_id,)
    )
    total = (await cur.fetchone())[0]
    cur = await db.conn.execute(
        "SELECT COUNT(*) FROM bot_users WHERE ref_link_id = ? AND is_alive = 1", (ref_id,)
    )
    alive = (await cur.fetchone())[0]
    cur = await db.conn.execute(
        "SELECT COUNT(*) FROM bot_users WHERE ref_link_id = ? AND is_premium = 1", (ref_id,)
    )
    prem = (await cur.fetchone())[0]
    cur = await db.conn.execute(
        "SELECT COUNT(*) FROM bot_users WHERE ref_link_id = ? AND completed = 1", (ref_id,)
    )
    done = (await cur.fetchone())[0]

    text = (
        f"<b>🔗 {ref['name'] or ref['code']}</b>\n\n"
        f"Код: <code>{ref['code']}</code>\n"
        f"Ссылка: <code>{link}</code>\n\n"
        f"👥 Всего: <b>{total}</b>\n"
        f"🟢 Живых: {alive}\n"
        f"🪦 Мёртвых: {total - alive}\n"
        f"⭐️ Премиум: {prem}\n"
        f"🏁 Завершили: {done}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗑 Удалить", callback_data=f"ref_del:{ref_id}")],
        [InlineKeyboardButton(text="« К ссылкам", callback_data=f"refs:{ref['bot_id']}")],
    ])
    await cb.message.edit_text(text, reply_markup=kb)
    await cb.answer()


@router.callback_query(F.data.startswith("ref_del:"))
async def cb_ref_del(cb: CallbackQuery) -> None:
    if not is_admin(cb.from_user.id):
        await cb.answer("⛔", show_alert=True)
        return
    ref_id = int(cb.data.split(":")[1])
    ref = await get_db().get_ref_link(ref_id)
    if not ref:
        await cb.answer("Не найдено", show_alert=True)
        return
    bot_id = ref["bot_id"]
    await get_db().delete_ref_link(ref_id)
    refs = await get_db().list_ref_links(bot_id)
    await cb.message.edit_text("🗑 Ссылка удалена.", reply_markup=_refs_kb(bot_id, refs))
    await cb.answer()
