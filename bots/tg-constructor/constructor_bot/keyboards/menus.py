"""
Reusable inline keyboards for the constructor bot.
"""
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def main_menu_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🤖 Мои боты", callback_data="bots_list"))
    builder.row(InlineKeyboardButton(text="➕ Добавить бота", callback_data="add_bot"))
    return builder.as_markup()


def bots_list_kb(bots: list) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for bot in bots:
        status = "✅" if bot.is_active else "⏸"
        builder.row(InlineKeyboardButton(
            text=f"{status} {bot.name}",
            callback_data=f"bot_menu:{bot.id}"
        ))
    builder.row(InlineKeyboardButton(text="➕ Добавить бота", callback_data="add_bot"))
    builder.row(InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu"))
    return builder.as_markup()


def bot_menu_kb(bot_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="📋 Сценарий", callback_data=f"scenario:{bot_id}"))
    builder.row(InlineKeyboardButton(text="📊 Статистика", callback_data=f"stats:{bot_id}"))
    builder.row(InlineKeyboardButton(text="📣 Рассылка", callback_data=f"broadcast:{bot_id}"))
    builder.row(InlineKeyboardButton(text="⚙️ Настройки", callback_data=f"bot_settings:{bot_id}"))
    builder.row(
        InlineKeyboardButton(text="⏸ Пауза / ▶️ Запуск", callback_data=f"toggle_bot:{bot_id}"),
        InlineKeyboardButton(text="🗑 Удалить", callback_data=f"delete_bot:{bot_id}")
    )
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="bots_list"))
    return builder.as_markup()


def scenario_menu_kb(bot_id: int, steps: list) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for step in steps:
        icon = {"message": "💬", "op": "🔒", "wait": "⏳"}.get(step.step_type, "❓")
        builder.row(InlineKeyboardButton(
            text=f"{icon} Шаг {step.position + 1}: {step.step_type}",
            callback_data=f"step_menu:{step.id}"
        ))
    builder.row(InlineKeyboardButton(text="➕ Добавить шаг", callback_data=f"add_step:{bot_id}"))
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data=f"bot_menu:{bot_id}"))
    return builder.as_markup()


def add_step_type_kb(bot_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="💬 Сообщение", callback_data=f"new_step:message:{bot_id}"))
    builder.row(InlineKeyboardButton(text="🔒 ОП (обязательная подписка)", callback_data=f"new_step:op:{bot_id}"))
    builder.row(InlineKeyboardButton(text="🎰 Рулетка (мини-апп)", callback_data=f"add_roulette:{bot_id}"))
    builder.row(InlineKeyboardButton(text="◀️ Отмена", callback_data=f"scenario:{bot_id}"))
    return builder.as_markup()


def step_menu_kb(step_id: int, bot_id: int, step_type: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="✏️ Изменить сообщение", callback_data=f"edit_step_msg:{step_id}"))
    if step_type == "op":
        builder.row(InlineKeyboardButton(text="📢 Спонсоры", callback_data=f"sponsors:{step_id}"))
    builder.row(InlineKeyboardButton(text="⏱ Задержка после шага", callback_data=f"set_delay:{step_id}"))
    builder.row(InlineKeyboardButton(text="🔔 Текст ожидания", callback_data=f"set_wait_text:{step_id}"))
    builder.row(
        InlineKeyboardButton(text="⬆️", callback_data=f"step_up:{step_id}:{bot_id}"),
        InlineKeyboardButton(text="⬇️", callback_data=f"step_down:{step_id}:{bot_id}"),
        InlineKeyboardButton(text="🗑", callback_data=f"delete_step:{step_id}:{bot_id}"),
    )
    builder.row(InlineKeyboardButton(text="◀️ Назад к сценарию", callback_data=f"scenario:{bot_id}"))
    return builder.as_markup()


def sponsors_kb(step_id: int, sponsors: list) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for sp in sponsors:
        builder.row(InlineKeyboardButton(
            text=f"📢 {sp.title}",
            callback_data=f"del_sponsor:{sp.id}:{step_id}"
        ))
    builder.row(InlineKeyboardButton(text="➕ Добавить спонсора", callback_data=f"add_sponsor:{step_id}"))
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data=f"step_menu:{step_id}"))
    return builder.as_markup()


def cancel_kb(callback_data: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data=callback_data))
    return builder.as_markup()


def confirm_delete_kb(confirm_cb: str, cancel_cb: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Да, удалить", callback_data=confirm_cb),
        InlineKeyboardButton(text="❌ Отмена", callback_data=cancel_cb)
    )
    return builder.as_markup()


def back_kb(callback_data: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data=callback_data))
    return builder.as_markup()
