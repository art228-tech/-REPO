"""Инлайн-клавиатуры, используемые ботом."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def admin_panel() -> InlineKeyboardMarkup:
    """Инлайн-клавиатура админ-панели."""
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="Статистика", callback_data="admin:stats"))
    builder.row(InlineKeyboardButton(text="Рассылка", callback_data="admin:broadcast"))
    builder.row(InlineKeyboardButton(text="Закрыть", callback_data="admin:close"))
    return builder.as_markup()


def cancel_keyboard() -> InlineKeyboardMarkup:
    """Одна кнопка «Отмена» для пошаговых сценариев."""
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="Отмена", callback_data="admin:cancel"))
    return builder.as_markup()
