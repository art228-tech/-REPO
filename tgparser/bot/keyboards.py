"""Инлайн-клавиатуры."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from tgparser.db.settings_store import Pace, ScanSettings


def main_menu(has_account: bool, scanning: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if not has_account:
        builder.button(text="Подключить аккаунт", callback_data="auth:start")
    else:
        if scanning:
            builder.button(text="Остановить обход", callback_data="scan:stop")
            builder.button(text="Статус", callback_data="scan:status")
        else:
            builder.button(text="Запустить обход", callback_data="scan:start")
            builder.button(text="Продолжить с места остановки", callback_data="scan:resume")
        builder.button(text="База", callback_data="db:menu")
        builder.button(text="Выгрузить", callback_data="export:menu")
        builder.button(text="Настройки", callback_data="settings:menu")
        builder.button(text="Аккаунт", callback_data="auth:info")
    builder.adjust(1)
    return builder.as_markup()


def proxy_choice(current: str | None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if current:
        builder.button(text="Оставить как есть", callback_data="proxy:keep")
        builder.button(text="Изменить прокси", callback_data="proxy:set")
        builder.button(text="Убрать прокси", callback_data="proxy:clear")
    else:
        builder.button(text="Без прокси", callback_data="proxy:keep")
        builder.button(text="Указать прокси", callback_data="proxy:set")
    builder.button(text="Отмена", callback_data="menu:main")
    builder.adjust(1)
    return builder.as_markup()


def keys_choice(has_shared: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Получить ключи автоматически", callback_data="keys:auto")
    builder.button(text="Ввести свои api_id и api_hash", callback_data="keys:manual")
    if has_shared:
        builder.button(text="Использовать общие ключи бота", callback_data="keys:shared")
    builder.button(text="Отмена", callback_data="menu:main")
    builder.adjust(1)
    return builder.as_markup()


def keys_retry() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Попробовать снова", callback_data="keys:auto")
    builder.button(text="Ввести ключи руками", callback_data="keys:manual")
    builder.button(text="Отмена", callback_data="menu:main")
    builder.adjust(1)
    return builder.as_markup()


def code_keypad(masked: str) -> InlineKeyboardMarkup:
    """Пад для ввода кода.

    Цифры набираются кнопками, потому что код, отправленный сообщением внутри
    Telegram, сервер гасит. Нажатие кнопки — callback query, не сообщение.
    """
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text=f"Код: {masked or '·····'}", callback_data="code:noop")]
    ]
    for line in ("123", "456", "789"):
        rows.append(
            [InlineKeyboardButton(text=d, callback_data=f"code:digit:{d}") for d in line]
        )
    rows.append(
        [
            InlineKeyboardButton(text="⌫", callback_data="code:back"),
            InlineKeyboardButton(text="0", callback_data="code:digit:0"),
            InlineKeyboardButton(text="Готово", callback_data="code:submit"),
        ]
    )
    rows.append([InlineKeyboardButton(text="Отменить вход", callback_data="code:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _flag(value: bool) -> str:
    return "вкл" if value else "выкл"


def settings_menu(s: ScanSettings) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    depth = "без ограничения" if s.history_depth_days <= 0 else f"{s.history_depth_days} дн."
    builder.button(text=f"Глубина истории: {depth}", callback_data="settings:depth")
    builder.button(
        text=f"Авторы сообщений: {_flag(s.collect_history)}",
        callback_data="settings:toggle:collect_history",
    )
    builder.button(
        text=f"Комментарии каналов: {_flag(s.collect_comments)}",
        callback_data="settings:toggle:collect_comments",
    )
    builder.button(
        text=f"Сообщения о вступлении: {_flag(s.collect_joins)}",
        callback_data="settings:toggle:collect_joins",
    )
    builder.button(
        text=f"Список участников: {_flag(s.collect_roster)}",
        callback_data="settings:toggle:collect_roster",
    )
    builder.button(
        text=f"Пересылать безтеговых: {_flag(s.forward_untagged)}",
        callback_data="settings:toggle:forward_untagged",
    )
    builder.button(
        text=f"Пропускать ботов: {_flag(s.skip_bots)}",
        callback_data="settings:toggle:skip_bots",
    )
    builder.button(
        text=f"Только активный топик: {_flag(s.forum_busiest_topic_only)}",
        callback_data="settings:toggle:forum_busiest_topic_only",
    )
    builder.button(
        text=f"Пропускать архив: {_flag(s.skip_archived)}",
        callback_data="settings:toggle:skip_archived",
    )
    builder.button(text="Отбор чатов", callback_data="settings:chats")
    builder.button(text="Темп и лимиты", callback_data="settings:pace")
    builder.button(text="Назад", callback_data="menu:main")
    builder.adjust(1)
    return builder.as_markup()


def chats_menu(s: ScanSettings) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    only = len(s.included_chats)
    skip = len(s.excluded_chats)
    builder.button(
        text=f"Только эти чаты: {only or 'все'}", callback_data="settings:chats:only"
    )
    builder.button(
        text=f"Исключить чаты: {skip or 'нет'}", callback_data="settings:chats:skip"
    )
    builder.button(
        text=f"Минимум участников: {s.min_participants or 'без ограничения'}",
        callback_data="settings:chats:min",
    )
    if only:
        builder.button(text="Сбросить «только эти»", callback_data="settings:chats:clear:only")
    if skip:
        builder.button(text="Сбросить исключения", callback_data="settings:chats:clear:skip")
    builder.button(text="Назад", callback_data="settings:menu")
    builder.adjust(1)
    return builder.as_markup()


def depth_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for days, label in ((7, "7 дней"), (30, "30 дней"), (90, "90 дней"), (180, "полгода")):
        builder.button(text=label, callback_data=f"settings:depth:{days}")
    builder.button(text="Без ограничения", callback_data="settings:depth:0")
    builder.button(text="Назад", callback_data="settings:menu")
    builder.adjust(2, 2, 1, 1)
    return builder.as_markup()


def pace_menu(s: ScanSettings, pace: Pace | None = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=f"Ростер: {s.roster_calls_per_hour} запр./час",
        callback_data="settings:pace:roster",
    )
    builder.button(
        text=f"История: {s.history_calls_per_hour} запр./час",
        callback_data="settings:pace:history",
    )
    if pace is not None and pace.throttled:
        builder.button(
            text="Снять понижение темпа", callback_data="settings:pace:warmup"
        )
    builder.button(text="Назад", callback_data="settings:menu")
    builder.adjust(1)
    return builder.as_markup()


def export_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="XLSX (Excel)", callback_data="export:fmt:xlsx")
    builder.button(text="CSV", callback_data="export:fmt:csv")
    builder.button(text="JSON", callback_data="export:fmt:json")
    builder.button(text="Только теги, txt", callback_data="export:fmt:txt")
    builder.button(text="Только с тегом → XLSX", callback_data="export:tagged:xlsx")
    builder.button(text="Назад", callback_data="menu:main")
    builder.adjust(2, 2, 1, 1)
    return builder.as_markup()


def db_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Добавить теги вручную", callback_data="db:add")
    builder.button(text="Статистика", callback_data="db:stats")
    builder.button(text="Очистить базу", callback_data="db:wipe")
    builder.button(text="Сбросить чекпоинты обхода", callback_data="db:reset")
    builder.button(text="Назад", callback_data="menu:main")
    builder.adjust(1)
    return builder.as_markup()


def account_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Настроить прокси", callback_data="proxy:edit")
    builder.button(text="Отключить аккаунт", callback_data="auth:logout")
    builder.button(text="Назад", callback_data="menu:main")
    builder.adjust(1)
    return builder.as_markup()


def confirm(action: str, back: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Да, подтверждаю", callback_data=action)
    builder.button(text="Отмена", callback_data=back)
    builder.adjust(1)
    return builder.as_markup()


def back_to(target: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Назад", callback_data=target)
    return builder.as_markup()
