"""Состояния диалогов."""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class AuthFlow(StatesGroup):
    phone = State()
    password = State()


class DatabaseFlow(StatesGroup):
    manual_tags = State()


class SettingsFlow(StatesGroup):
    roster_budget = State()
    history_budget = State()
