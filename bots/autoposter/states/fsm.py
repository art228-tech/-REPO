"""FSM-состояния автопостера v2."""
from aiogram.fsm.state import State, StatesGroup


class HelperStates(StatesGroup):
    wait_token = State()


class ChannelStates(StatesGroup):
    wait_helper_pick = State()  # выбор помощника при добавлении канала
    wait_forward = State()      # пересланный пост из канала


class TaskStates(StatesGroup):
    wait_name = State()
    wait_rename = State()


class PostStates(StatesGroup):
    wait_edit_next_delay = State()
    wait_edit_delete_after = State()
    wait_backup_url = State()
    wait_btn_color = State()
    wait_new_url = State()
    wait_content = State()
    wait_buttons_choice = State()
    wait_button_text = State()
    wait_button_url = State()
    wait_next_delay = State()
    wait_delete_after = State()
