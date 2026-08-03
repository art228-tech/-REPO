from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="👤 Аккаунты"), KeyboardButton(text="📇 База")],
            [KeyboardButton(text="✉️ Сообщения"), KeyboardButton(text="⚙️ Настройки")],
            [KeyboardButton(text="▶️ Старт"), KeyboardButton(text="⏹ Стоп")],
            [KeyboardButton(text="📊 Статистика"), KeyboardButton(text="📤 Выгрузка")],
            [KeyboardButton(text="🧾 Логи")],
        ],
        resize_keyboard=True,
    )


def accounts_kb(accounts) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text="➕ Добавить аккаунт", callback_data="acc:add")],
    ]
    for acc in accounts:
        mark = {"active": "🟢", "spamblock": "🔴", "error": "🟠"}.get(acc["status"], "⚪")
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{mark} #{acc['id']} {acc['phone']}",
                    callback_data=f"acc:view:{acc['id']}",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="🔄 Обновить", callback_data="acc:list")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def account_actions_kb(account_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🌐 Прокси", callback_data=f"acc:proxy:{account_id}"
                ),
                InlineKeyboardButton(
                    text="✅ Снять SB", callback_data=f"acc:unsb:{account_id}"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🩺 Проверка", callback_data=f"acc:check:{account_id}"
                ),
                InlineKeyboardButton(
                    text="🗑 Удалить", callback_data=f"acc:del:{account_id}"
                ),
            ],
            [InlineKeyboardButton(text="« Назад", callback_data="acc:list")],
        ]
    )


def messages_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Msg1 список", callback_data="msg:list:1"),
                InlineKeyboardButton(text="Msg2 список", callback_data="msg:list:2"),
            ],
            [
                InlineKeyboardButton(text="➕ Вариант Msg1", callback_data="msg:add:1"),
                InlineKeyboardButton(text="➕ Вариант Msg2", callback_data="msg:add:2"),
            ],
            [
                InlineKeyboardButton(text="🧹 Очистить Msg1", callback_data="msg:clear:1"),
                InlineKeyboardButton(text="🧹 Очистить Msg2", callback_data="msg:clear:2"),
            ],
        ]
    )


def variants_kb(slot: int, variants) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"🗑 #{v['id']} {v['text'][:30]}",
                callback_data=f"msg:del:{v['id']}:{slot}",
            )
        ]
        for v in variants
    ]
    rows.append([InlineKeyboardButton(text="➕ Добавить", callback_data=f"msg:add:{slot}")])
    rows.append([InlineKeyboardButton(text="« Назад", callback_data="msg:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def base_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📥 Загрузить (добавить)", callback_data="base:upload:add")],
            [InlineKeyboardButton(text="♻️ Загрузить (заменить)", callback_data="base:upload:replace")],
            [InlineKeyboardButton(text="🧹 Очистить базу", callback_data="base:clear")],
            [InlineKeyboardButton(text="📊 Сводка", callback_data="base:stats")],
        ]
    )


def export_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⏳ Pending (не получили)", callback_data="export:pending")],
            [InlineKeyboardButton(text="✅ Sent (получили)", callback_data="export:sent")],
            [InlineKeyboardButton(text="❌ Failed", callback_data="export:failed")],
            [InlineKeyboardButton(text="📋 Все", callback_data="export:all")],
        ]
    )


def settings_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="API_ID / API_HASH", callback_data="set:api")],
            [InlineKeyboardButton(text="Пауза msg1→msg2 (диапазон)", callback_data="set:delay_msg")],
            [InlineKeyboardButton(text="Интервал на аккаунт (диапазон)", callback_data="set:delay_acc")],
        ]
    )


def confirm_kb(action: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Да", callback_data=f"confirm:{action}:yes"),
                InlineKeyboardButton(text="Нет", callback_data=f"confirm:{action}:no"),
            ]
        ]
    )


def cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")]
        ]
    )


def code_pad_kb(entered: str = "") -> InlineKeyboardMarkup:
    """Inline numpad: code never goes into chat text (TG won't invalidate it)."""
    mask = "•" * len(entered) if entered else "—"
    rows = [
        [InlineKeyboardButton(text=f"Код: {mask}", callback_data="code:noop")],
        [
            InlineKeyboardButton(text="1", callback_data="code:d:1"),
            InlineKeyboardButton(text="2", callback_data="code:d:2"),
            InlineKeyboardButton(text="3", callback_data="code:d:3"),
        ],
        [
            InlineKeyboardButton(text="4", callback_data="code:d:4"),
            InlineKeyboardButton(text="5", callback_data="code:d:5"),
            InlineKeyboardButton(text="6", callback_data="code:d:6"),
        ],
        [
            InlineKeyboardButton(text="7", callback_data="code:d:7"),
            InlineKeyboardButton(text="8", callback_data="code:d:8"),
            InlineKeyboardButton(text="9", callback_data="code:d:9"),
        ],
        [
            InlineKeyboardButton(text="⌫", callback_data="code:del"),
            InlineKeyboardButton(text="0", callback_data="code:d:0"),
            InlineKeyboardButton(text="✅ OK", callback_data="code:ok"),
        ],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)