"""FSM-состояния админского интерфейса."""
from aiogram.fsm.state import State, StatesGroup


class AddBotStates(StatesGroup):
    waiting_for_token = State()


class StepStates(StatesGroup):
    # Общие
    select_type = State()

    # Сообщение
    msg_content = State()                # ждём контент (текст/фото/...)
    msg_add_buttons = State()             # добавление кнопок
    msg_add_button_text = State()
    msg_add_button_url = State()
    msg_add_button_color = State()
    msg_wait_mode = State()               # таймер / любое сообщение / без ожидания
    msg_wait_timer = State()              # вводим число секунд
    msg_keyboard_choice = State()         # добавлять ли кнопку клавы
    msg_keyboard_text = State()           # текст кнопки клавы
    msg_duplicate_after = State()
    msg_duplicate_increment = State()
    msg_duplicate_max = State()

    # ОП
    op_content = State()
    op_add_sponsor = State()              # текст подсказки
    op_sponsor_check = State()            # с проверкой или нет
    op_sponsor_channel_id = State()
    op_sponsor_link = State()
    op_sponsor_title = State()
    op_sponsor_button_text = State()
    op_sponsor_button_color = State()
    op_check_btn_text = State()
    op_check_btn_color = State()
    op_duplicate_after = State()
    op_duplicate_increment = State()
    op_duplicate_max = State()

    # Рулетка
    roulette_content = State()
    roulette_button_text = State()
    roulette_button_color = State()
    roulette_duplicate_after = State()
    roulette_duplicate_increment = State()
    roulette_duplicate_max = State()


class BotSettingsStates(StatesGroup):
    join_delay = State()
    delete_timer = State()


class RefStates(StatesGroup):
    name = State()


class BroadcastStates(StatesGroup):
    content = State()
    confirm = State()
