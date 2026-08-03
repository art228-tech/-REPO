from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class AddAccountSG(StatesGroup):
    phone = State()
    code = State()
    password = State()
    proxy = State()


class SetProxySG(StatesGroup):
    value = State()


class MessagesSG(StatesGroup):
    add_text = State()


class BaseSG(StatesGroup):
    upload = State()


class SettingsSG(StatesGroup):
    api_id = State()
    api_hash = State()
    delay_msg = State()
    delay_acc = State()