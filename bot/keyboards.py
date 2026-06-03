"""Inline keyboards used by the bot."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def admin_panel() -> InlineKeyboardMarkup:
    """Inline keyboard for the admin panel."""
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="Statistics", callback_data="admin:stats"))
    builder.row(InlineKeyboardButton(text="Broadcast", callback_data="admin:broadcast"))
    builder.row(InlineKeyboardButton(text="Close", callback_data="admin:close"))
    return builder.as_markup()


def cancel_keyboard() -> InlineKeyboardMarkup:
    """Single 'Cancel' button used during multi-step flows."""
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="Cancel", callback_data="admin:cancel"))
    return builder.as_markup()
