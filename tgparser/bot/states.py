"""Состояния диалогов."""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class AuthFlow(StatesGroup):
    phone = State()
    keys = State()
    manual_keys = State()
    # Код с my.telegram.org приходит буквенно-цифровым, поэтому его ждём
    # сообщением, а не набором на паде.
    portal_code = State()
    password = State()


class DatabaseFlow(StatesGroup):
    manual_tags = State()


class SettingsFlow(StatesGroup):
    roster_budget = State()
    history_budget = State()
    included_chats = State()
    excluded_chats = State()
    min_participants = State()
