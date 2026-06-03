"""Клавиатуры автопостера."""
from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Каналы", callback_data="channels")],
        [InlineKeyboardButton(text="📋 Задачи", callback_data="tasks")],
        [InlineKeyboardButton(text="▶️ Автопостинг", callback_data="posting")],
    ])


def channels_menu(channels: list) -> InlineKeyboardMarkup:
    rows = []
    for ch in channels:
        rows.append([InlineKeyboardButton(
            text=f"📢 {ch['title']}", callback_data=f"ch:{ch['id']}")])
    rows.append([InlineKeyboardButton(text="➕ Добавить канал", callback_data="ch_add")])
    rows.append([InlineKeyboardButton(text="« Меню", callback_data="menu")])
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
    rows.append([InlineKeyboardButton(text="✏️ Переименовать задачу", callback_data=f"task_ren:{task_id}")])
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
    rows.append([InlineKeyboardButton(text="🗑 Удалить пост", callback_data=f"post_del:{post_id}")])
    rows.append([InlineKeyboardButton(text="« К задаче", callback_data=f"task:{task_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def buttons_choice() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить кнопку", callback_data="pbtn:add")],
        [InlineKeyboardButton(text="✅ Готово (без кнопок / закончить)", callback_data="pbtn:done")],
    ])
