"""FSM-состояния автоприёма v2."""
from aiogram.fsm.state import State, StatesGroup


class HelperStates(StatesGroup):
    wait_token = State()


class ChannelStates(StatesGroup):
    wait_helper_pick = State()
    wait_forward = State()
    wait_delay = State()
