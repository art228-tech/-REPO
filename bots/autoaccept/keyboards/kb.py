"""Клавиатуры автоприёма v2."""
from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🤖 Помощники", callback_data="helpers")],
        [InlineKeyboardButton(text="📢 Каналы", callback_data="channels")],
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
        h_name = (helper["name"] or helper["username"]) if helper else "?"
        on = "🟢" if ch["auto_accept"] else "⚪"
        rows.append([InlineKeyboardButton(
            text=f"{on} {ch['title']} ← {h_name}",
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


def channel_card(ch) -> InlineKeyboardMarkup:
    on = "🟢 Автоприём вкл" if ch["auto_accept"] else "⚪ Автоприём выкл"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=on, callback_data=f"ch_toggle:{ch['id']}")],
        [InlineKeyboardButton(
            text=f"⏱ Задержка: {ch['accept_delay']} с",
            callback_data=f"ch_delay:{ch['id']}")],
        [InlineKeyboardButton(text="🗑 Удалить канал", callback_data=f"ch_del:{ch['id']}")],
        [InlineKeyboardButton(text="« К каналам", callback_data="channels")],
    ])
