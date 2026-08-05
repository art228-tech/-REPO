"""Клавиатуры автопостера v2."""
from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🤖 Помощники", callback_data="helpers")],
        [InlineKeyboardButton(text="📢 Каналы", callback_data="channels")],
        [InlineKeyboardButton(text="📋 Задачи", callback_data="tasks")],
        [InlineKeyboardButton(text="▶️ Автопостинг", callback_data="posting")],
    ])


def helpers_menu(helpers: list) -> InlineKeyboardMarkup:
    rows = []
    for h in helpers:
        mark = "🟢" if h["is_alive"] else "💀"
        name = h["name"] or h["username"] or f"id{h['id']}"
        rows.append([InlineKeyboardButton(
            text=f"{mark} {name}", callback_data=f"h:{h['id']}")])
    rows.append([InlineKeyboardButton(text="➕ Добавить помощника", callback_data="h_add")])
    rows.append([InlineKeyboardButton(text="« Меню", callback_data="menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def helper_card(h_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗑 Удалить помощника", callback_data=f"h_del:{h_id}")],
        [InlineKeyboardButton(text="« К помощникам", callback_data="helpers")],
    ])


def channels_menu(channels: list, helpers_by_id: dict) -> InlineKeyboardMarkup:
    rows = []
    for ch in channels:
        helper = helpers_by_id.get(ch["helper_id"])
        h_name = helper["name"] or helper["username"] if helper else "?"
        rows.append([InlineKeyboardButton(
            text=f"📢 {ch['title']} ← {h_name}",
            callback_data=f"ch:{ch['id']}")])
    rows.append([InlineKeyboardButton(text="➕ Добавить канал", callback_data="ch_add")])
    rows.append([InlineKeyboardButton(text="« Меню", callback_data="menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def helper_pick_for_channel(helpers: list) -> InlineKeyboardMarkup:
    rows = []
    for h in helpers:
        if not h["is_alive"]:
            continue
        name = h["name"] or h["username"] or f"id{h['id']}"
        rows.append([InlineKeyboardButton(
            text=f"🤖 {name}", callback_data=f"ch_pick_h:{h['id']}")])
    rows.append([InlineKeyboardButton(text="« Отмена", callback_data="channels")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def channel_card(ch_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗑 Удалить канал", callback_data=f"ch_del:{ch_id}")],
        [InlineKeyboardButton(text="« К каналам", callback_data="channels")],
    ])


def tasks_menu(tasks: list) -> InlineKeyboardMarkup:
    rows = []
    for t in tasks:
        rows.append([InlineKeyboardButton(
            text=f"📋 {t['name']}", callback_data=f"task:{t['id']}")])
    rows.append([InlineKeyboardButton(text="➕ Новая задача", callback_data="task_add")])
    rows.append([InlineKeyboardButton(text="« Меню", callback_data="menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def task_card(task_id: int, posts: list) -> InlineKeyboardMarkup:
    rows = []
    for i, p in enumerate(posts, 1):
        rows.append([InlineKeyboardButton(
            text=f"✏️ Пост {i}", callback_data=f"post:{p['id']}")])
    rows.append([InlineKeyboardButton(text="➕ Добавить пост", callback_data=f"post_add:{task_id}")])
    rows.append([InlineKeyboardButton(text="✏️ Переименовать", callback_data=f"task_ren:{task_id}")])
    rows.append([InlineKeyboardButton(text="🗑 Удалить задачу", callback_data=f"task_del:{task_id}")])
    rows.append([InlineKeyboardButton(text="« К задачам", callback_data="tasks")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def post_card(post_id: int, task_id: int, idx: int, total: int) -> InlineKeyboardMarkup:
    rows = []
    move = []
    if idx > 0:
        move.append(InlineKeyboardButton(text="⬆️ Вверх", callback_data=f"post_up:{post_id}"))
    if idx < total - 1:
        move.append(InlineKeyboardButton(text="⬇️ Вниз", callback_data=f"post_down:{post_id}"))
    if move:
        rows.append(move)
    rows.append([InlineKeyboardButton(text="🔗 Ссылки", callback_data=f"post_links:{post_id}")])
    rows.append([InlineKeyboardButton(text="🎨 Цвет кнопок", callback_data=f"post_color:{post_id}")])
    rows.append([
        InlineKeyboardButton(text="⏱ Время постинга", callback_data=f"post_edt_nd:{post_id}"),
        InlineKeyboardButton(text="🗑 Автоудаление", callback_data=f"post_edt_da:{post_id}"),
    ])
    rows.append([InlineKeyboardButton(text="🗑 Удалить", callback_data=f"post_del:{post_id}")])
    rows.append([InlineKeyboardButton(text="« К задаче", callback_data=f"task:{task_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def buttons_choice() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить кнопку", callback_data="pbtn:add")],
        [InlineKeyboardButton(text="✅ Готово", callback_data="pbtn:done")],
    ])


def buttons_color_choice() -> InlineKeyboardMarkup:
    """Выбор цвета кнопок (Bot API 9.4 style)."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🟢 Зелёные", callback_data="pcolor:success")],
        [InlineKeyboardButton(text="🔴 Красные", callback_data="pcolor:danger")],
        [InlineKeyboardButton(text="🔵 Синие", callback_data="pcolor:primary")],
        [InlineKeyboardButton(text="⚪ Без цвета", callback_data="pcolor:none")],
    ])


def post_color_choice(post_id: int) -> InlineKeyboardMarkup:
    """Смена цвета кнопок существующего поста."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🟢 Зелёные", callback_data=f"pcol:{post_id}:success")],
        [InlineKeyboardButton(text="🔴 Красные", callback_data=f"pcol:{post_id}:danger")],
        [InlineKeyboardButton(text="🔵 Синие", callback_data=f"pcol:{post_id}:primary")],
        [InlineKeyboardButton(text="⚪ Без цвета", callback_data=f"pcol:{post_id}:none")],
        [InlineKeyboardButton(text="« К посту", callback_data=f"post:{post_id}")],
    ])
