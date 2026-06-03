"""FSM-состояния автопостера."""
from aiogram.fsm.state import State, StatesGroup


class ChannelStates(StatesGroup):
    wait_forward = State()      # ждём пересланное сообщение из канала


class TaskStates(StatesGroup):
    wait_name = State()         # имя новой задачи
    wait_rename = State()       # новое имя задачи


class PostStates(StatesGroup):
    wait_content = State()      # контент поста (текст/медиа) или пересланный пост
    wait_buttons_choice = State()  # добавлять ли кнопки
    wait_button_text = State()
    wait_button_url = State()
    wait_next_delay = State()   # через сколько к следующему посту
    wait_delete_after = State() # через сколько удалять пост
