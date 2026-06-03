"""Раздел «Автопостинг»: выбор канала, задач, запуск/стоп."""
from __future__ import annotations

import json
import time

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from database import get_db
from handlers.common import is_admin

router = Router()


# ===== Список каналов для постинга =====
@router.callback_query(F.data == "posting")
async def cb_posting(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        await cb.answer("⛔", show_alert=True)
        return
    await state.clear()
    db = get_db()
    channels = await db.list_channels()
    if not channels:
        await cb.message.edit_text(
            "📢 Сначала добавь хотя бы один канал в разделе «Каналы».",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="« Меню", callback_data="menu")],
            ]),
        )
        await cb.answer()
        return
    rows = []
    for ch in channels:
        st = await db.get_posting_state(ch["id"])
        mark = "🟢" if (st and st["is_running"]) else "⚪"
        rows.append([InlineKeyboardButton(
            text=f"{mark} {ch['title']}", callback_data=f"pst:{ch['id']}")])
    rows.append([InlineKeyboardButton(text="« Меню", callback_data="menu")])
    await cb.message.edit_text(
        "<b>▶️ Автопостинг</b>\n\n🟢 — идёт, ⚪ — остановлен.\nВыбери канал:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await cb.answer()


async def _render_channel_posting(cb: CallbackQuery, ch_id: int) -> None:
    db = get_db()
    ch = await db.get_channel(ch_id)
    if not ch:
        await cb.answer("Канал не найден", show_alert=True)
        return
    st = await db.get_posting_state(ch_id)
    running = bool(st and st["is_running"])
    sel = []
    if st and st["task_ids"]:
        try:
            sel = json.loads(st["task_ids"])
        except Exception:
            sel = []
    tasks = await db.list_tasks()

    rows = []
    for t in tasks:
        posts = await db.list_posts(t["id"])
        mark = "✅" if t["id"] in sel else "▫️"
        rows.append([InlineKeyboardButton(
            text=f"{mark} {t['name']} ({len(posts)} постов)",
            callback_data=f"pst_t:{ch_id}:{t['id']}")])
    if running:
        rows.append([InlineKeyboardButton(
            text="⏹ Остановить автопостинг", callback_data=f"pst_stop:{ch_id}")])
    else:
        rows.append([InlineKeyboardButton(
            text="▶️ Запустить автопостинг", callback_data=f"pst_start:{ch_id}")])
    rows.append([InlineKeyboardButton(text="« К каналам", callback_data="posting")])

    status = "🟢 идёт" if running else "⚪ остановлен"
    txt = (
        f"<b>▶️ Автопостинг — {ch['title']}</b>\n\n"
        f"Статус: {status}\n"
        f"Выбрано задач: {len(sel)}\n\n"
        "Отметь задачи галочкой (постятся по кругу в порядке отметки), "
        "затем запусти."
    )
    await cb.message.edit_text(
        txt, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)
    )


@router.callback_query(F.data.startswith("pst:"))
async def cb_posting_channel(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        return
    ch_id = int(cb.data.split(":")[1])
    await _render_channel_posting(cb, ch_id)
    await cb.answer()


# ===== Переключение задачи в выборе =====
@router.callback_query(F.data.startswith("pst_t:"))
async def cb_posting_toggle_task(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        return
    _, ch_id, task_id = cb.data.split(":")
    ch_id, task_id = int(ch_id), int(task_id)
    db = get_db()
    st = await db.get_posting_state(ch_id)
    if st and st["is_running"]:
        await cb.answer("Сначала останови автопостинг", show_alert=True)
        return
    sel = []
    if st and st["task_ids"]:
        try:
            sel = json.loads(st["task_ids"])
        except Exception:
            sel = []
    if task_id in sel:
        sel.remove(task_id)
    else:
        sel.append(task_id)
    await db.set_posting_state(ch_id, task_ids=json.dumps(sel))
    await _render_channel_posting(cb, ch_id)
    await cb.answer()


# ===== Запуск =====
@router.callback_query(F.data.startswith("pst_start:"))
async def cb_posting_start(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        return
    ch_id = int(cb.data.split(":")[1])
    db = get_db()
    st = await db.get_posting_state(ch_id)
    sel = []
    if st and st["task_ids"]:
        try:
            sel = json.loads(st["task_ids"])
        except Exception:
            sel = []
    if not sel:
        await cb.answer("Отметь хотя бы одну задачу", show_alert=True)
        return
    # проверяем что есть посты
    total_posts = 0
    for tid in sel:
        total_posts += len(await db.list_posts(tid))
    if total_posts == 0:
        await cb.answer("В выбранных задачах нет постов", show_alert=True)
        return
    # запускаем: указатель в начало, первый пост — сразу
    await db.set_posting_state(
        ch_id, is_running=1, cur_task_idx=0, cur_post_idx=0,
        next_fire_at=int(time.time()),
    )
    await _render_channel_posting(cb, ch_id)
    await cb.answer("▶️ Автопостинг запущен")


# ===== Стоп =====
@router.callback_query(F.data.startswith("pst_stop:"))
async def cb_posting_stop(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        return
    ch_id = int(cb.data.split(":")[1])
    await get_db().set_posting_state(ch_id, is_running=0)
    await _render_channel_posting(cb, ch_id)
    await cb.answer("⏹ Остановлено")
