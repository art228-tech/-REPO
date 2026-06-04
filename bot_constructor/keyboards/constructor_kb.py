"""Клавиатуры (inline) для админ-бота-конструктора."""
from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from utils.helpers import STYLE_LABELS


def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🤖 Мои приветки", callback_data="mybots")],
        [InlineKeyboardButton(text="➕ Добавить приветку", callback_data="addbot")],
        [InlineKeyboardButton(text="❓ Помощь", callback_data="help")],
    ])


def bots_list(bots: list) -> InlineKeyboardMarkup:
    rows = []
    for b in bots:
        title = b["name"] or b["username"] or f"bot {b['tg_id']}"
        rows.append([InlineKeyboardButton(
            text=f"🤖 @{b['username']} — {title}",
            callback_data=f"bot:{b['id']}",
        )])
    rows.append([InlineKeyboardButton(text="➕ Добавить", callback_data="addbot")])
    rows.append([InlineKeyboardButton(text="« Назад", callback_data="main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def bot_menu(bot_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📜 Сценарий", callback_data=f"scn:{bot_id}")],
        [InlineKeyboardButton(text="⚙️ Настройки", callback_data=f"set:{bot_id}")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data=f"stat:{bot_id}")],
        [InlineKeyboardButton(text="📣 Рассылка", callback_data=f"bc:{bot_id}")],
        [InlineKeyboardButton(text="🔗 Реф-ссылки", callback_data=f"refs:{bot_id}")],
        [InlineKeyboardButton(text="📊 Ссылки канала", callback_data=f"chlinks:{bot_id}")],
        [InlineKeyboardButton(text="🗑 Удалить приветку", callback_data=f"delbot:{bot_id}")],
        [InlineKeyboardButton(text="« К списку", callback_data="mybots")],
    ])


def settings_menu(bot_id: int, join_delay: int, delete_timer: int,
                  typing_mode: int = 0) -> InlineKeyboardMarkup:
    _tm = "✍️ С имитацией печати" if typing_mode else "💬 Обычная"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"⏱ Задержка перед стартом: {join_delay} с",
            callback_data=f"set_jd:{bot_id}",
        )],
        [InlineKeyboardButton(
            text=f"🗑 Таймер удаления старых: {delete_timer} с",
            callback_data=f"set_dt:{bot_id}",
        )],
        [InlineKeyboardButton(
            text=f"Вид приветки: {_tm}",
            callback_data=f"set_tm:{bot_id}",
        )],
        [InlineKeyboardButton(
            text="📢 Каналы приветки",
            callback_data=f"wch:{bot_id}",
        )],
        [InlineKeyboardButton(text="« Назад", callback_data=f"bot:{bot_id}")],
    ])


def scenario_menu(bot_id: int, steps: list) -> InlineKeyboardMarkup:
    rows = []
    type_emoji = {"roulette": "🎰", "op": "📢", "message": "💬"}
    for s in steps:
        emoji = type_emoji.get(s["step_type"], "·")
        # ⚠️ — оригинал скопированного поста удалён
        try:
            broken = s["copy_broken"]
        except (KeyError, IndexError):
            broken = 0
        warn = " ⚠️ оригинал удалён" if broken else ""
        rows.append([InlineKeyboardButton(
            text=f"{s['step_order']+1}. {emoji} {s['step_type']}{warn}",
            callback_data=f"step:{s['id']}",
        )])
    rows.append([InlineKeyboardButton(text="➕ Добавить шаг", callback_data=f"addstep:{bot_id}")])
    rows.append([InlineKeyboardButton(text="« Назад", callback_data=f"bot:{bot_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def add_step_type(bot_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎰 Рулетка", callback_data=f"newstep:{bot_id}:roulette")],
        [InlineKeyboardButton(text="📢 Обязательная подписка", callback_data=f"newstep:{bot_id}:op")],
        [InlineKeyboardButton(text="💬 Сообщение", callback_data=f"newstep:{bot_id}:message")],
        [InlineKeyboardButton(text="« Назад", callback_data=f"scn:{bot_id}")],
    ])


def step_view(step_id: int, bot_id: int, step_type: str = "") -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text="⬆️ Вверх", callback_data=f"step_up:{step_id}"),
            InlineKeyboardButton(text="⬇️ Вниз", callback_data=f"step_dn:{step_id}"),
        ],
        [InlineKeyboardButton(text="👁 Посмотреть текст", callback_data=f"step_txt:{step_id}")],
        [InlineKeyboardButton(text="🔗 Ссылки", callback_data=f"step_links:{step_id}")],
    ]
    if step_type == "op":
        rows.append([InlineKeyboardButton(text="👥 Спонсоры", callback_data=f"spons:{step_id}")])
    rows.append([InlineKeyboardButton(text="🗑 Удалить шаг", callback_data=f"step_del:{step_id}")])
    rows.append([InlineKeyboardButton(text="« К сценарию", callback_data=f"scn:{bot_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def color_picker(prefix: str) -> InlineKeyboardMarkup:
    rows = []
    pairs = list(STYLE_LABELS.items())
    for i in range(0, len(pairs), 2):
        line = []
        for code, label in pairs[i : i + 2]:
            line.append(InlineKeyboardButton(text=label, callback_data=f"{prefix}:{code}"))
        rows.append(line)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def yes_no(yes_cb: str, no_cb: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Да", callback_data=yes_cb),
        InlineKeyboardButton(text="❌ Нет", callback_data=no_cb),
    ]])


def back_to(target: str, text: str = "« Назад") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=text, callback_data=target)]
    ])


def stats_menu(bot_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 Все юзеры", callback_data=f"st_all:{bot_id}")],
        [InlineKeyboardButton(text="⭐️ Премиум", callback_data=f"st_prem:{bot_id}")],
        [InlineKeyboardButton(text="🪦 Мёртвые", callback_data=f"st_dead:{bot_id}")],
        [InlineKeyboardButton(text="🔗 По реф-ссылкам", callback_data=f"st_refs:{bot_id}")],
        [InlineKeyboardButton(text="📊 По ссылкам канала", callback_data=f"st_chl:{bot_id}")],
        [InlineKeyboardButton(text="« Назад", callback_data=f"bot:{bot_id}")],
    ])


def msg_wait_mode_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏱ Таймер (X сек)", callback_data="wm:timer")],
        [InlineKeyboardButton(text="✉️ Любое сообщение", callback_data="wm:user_message")],
        [InlineKeyboardButton(text="🚫 Без ожидания (сразу дальше)", callback_data="wm:none")],
    ])


def add_button_now_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить кнопку", callback_data="btn:add")],
        [InlineKeyboardButton(text="✅ Готово", callback_data="btn:done")],
    ])


def add_sponsor_now_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить спонсора", callback_data="sp:add")],
        [InlineKeyboardButton(text="✅ Готово", callback_data="sp:done")],
    ])


def sponsor_check_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, проверять", callback_data="spc:1")],
        [InlineKeyboardButton(text="🚫 Нет, просто показывать", callback_data="spc:0")],
    ])
