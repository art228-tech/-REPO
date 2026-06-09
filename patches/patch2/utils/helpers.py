"""Хелперы: цвета кнопок (Bot API 9.4 style), рендер сообщений, парсинг."""
from __future__ import annotations

import logging
import re
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import (
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
)

log = logging.getLogger("helpers")


# Bot API 9.4 (февраль 2026) ввёл нативное поле style у кнопок.
# Доступные значения, которые Telegram отрисует в нужном цвете:
#   ""           — стандартная (белая)
#   "primary"    — синяя (акцентная)
#   "destructive"— красная
#   "success"    — зелёная
#   "secondary"  — серая (приглушённая)
#
# Помимо style поддерживается icon_custom_emoji_id — кастом-эмодзи слева
# от текста (премиум-стикер). Его может проставить любой бот, если эмодзи
# опубликован в премиум-наборе.
STYLE_LABELS = {
    "default":      "⚪ Стандартная",
    "primary":      "🔵 Синяя",
    "success":      "🟢 Зелёная",
    "destructive":  "🔴 Красная",
    "secondary":    "⚫ Серая",
}

# Алиасы, которые мы могли использовать раньше, мапим на новые style-значения,
# чтобы старые шаги в БД продолжили работать.
_LEGACY_TO_STYLE = {
    "default": "",
    "blue":    "primary",
    "green":   "success",
    "red":     "destructive",
    "yellow":  "secondary",
    "purple":  "primary",
    "orange":  "destructive",
    "white":   "",
    "black":   "secondary",
    "fire":    "destructive",
    "star":    "primary",
    "heart":   "destructive",
    "rocket":  "primary",
    "lock":    "secondary",
    "key":     "primary",
    "check":   "success",
    "cross":   "destructive",
    "gift":    "success",
    "primary":     "primary",
    "success":     "success",
    "destructive": "destructive",
    "secondary":   "secondary",
}

# Для обратной совместимости со старым API
COLOR_LABELS = STYLE_LABELS
COLOR_PREFIXES = {k: "" for k in _LEGACY_TO_STYLE}


def resolve_style(color: str | None) -> str:
    """Возвращает строку style для InlineKeyboardButton, либо '' (без style)."""
    if not color:
        return ""
    return _LEGACY_TO_STYLE.get(color, "")


# Старая функция оставлена ради совместимости, теперь возвращает текст без
# каких-либо эмодзи-префиксов (цвет теперь настоящий, префикс не нужен).
def color_button_text(text: str, color: str = "default") -> str:
    return text


_CUSTOM_EMOJI_RE = re.compile(
    r'<(?:tg-emoji|emoji)\s+emoji-id="(\d+)"[^>]*>.*?</(?:tg-emoji|emoji)>',
    re.IGNORECASE | re.DOTALL,
)


def extract_first_custom_emoji_id(text: str | None) -> str | None:
    """Возвращает emoji-id первого премиум-стикера в тексте, иначе None.

    Юзер при настройке кнопки может прислать сообщение с премиум-эмодзи —
    клиент Telegram пересылает его как <tg-emoji emoji-id="...">😀</tg-emoji>.
    Это число — id кастомного эмодзи, который мы пробросим в icon_custom_emoji_id.
    """
    if not text:
        return None
    m = _CUSTOM_EMOJI_RE.search(text)
    return m.group(1) if m else None


def strip_custom_emoji(text: str | None) -> str:
    """Убирает теги <tg-emoji ...>...</tg-emoji> из строки."""
    if not text:
        return ""
    return _CUSTOM_EMOJI_RE.sub("", text).strip()


def build_inline_keyboard(rows: list[list[dict[str, Any]]]) -> InlineKeyboardMarkup | None:
    """rows — список рядов. Каждая кнопка — dict: text, url|callback_data|web_app,
    color (style), custom_emoji_id (премиум-стикер слева)."""
    if not rows:
        return None
    built: list[list[InlineKeyboardButton]] = []
    for row in rows:
        line: list[InlineKeyboardButton] = []
        for btn in row:
            text = btn.get("text", "Кнопка")
            kwargs: dict[str, Any] = {"text": text}
            style_val = resolve_style(btn.get("color"))
            if style_val:
                kwargs["style"] = style_val
            cust = btn.get("custom_emoji_id")
            if cust:
                kwargs["icon_custom_emoji_id"] = str(cust)

            if btn.get("url"):
                kwargs["url"] = btn["url"]
            elif btn.get("callback_data"):
                kwargs["callback_data"] = btn["callback_data"]
            elif btn.get("web_app"):
                from aiogram.types import WebAppInfo
                kwargs["web_app"] = WebAppInfo(url=btn["web_app"])
            else:
                continue
            line.append(InlineKeyboardButton(**kwargs))
        if line:
            built.append(line)
    if not built:
        return None
    return InlineKeyboardMarkup(inline_keyboard=built)


def chunked(lst: list, size: int) -> list[list]:
    return [lst[i : i + size] for i in range(0, len(lst), size)]


async def safe_delete_message(bot: Bot, chat_id: int, message_id: int) -> bool:
    try:
        await bot.delete_message(chat_id, message_id)
        return True
    except (TelegramBadRequest, TelegramForbiddenError):
        return False
    except Exception:
        return False


def _resolve_media(value: str | None) -> Any:
    if not value:
        return None
    if isinstance(value, str) and value.startswith("path:"):
        return FSInputFile(value[5:])
    return value


async def send_step_message(
    bot: Bot,
    chat_id: int,
    *,
    text: str | None = None,
    photo_file_id: str | None = None,
    sticker_file_id: str | None = None,
    animation_file_id: str | None = None,
    video_file_id: str | None = None,
    document_file_id: str | None = None,
    copy_from: dict | None = None,
    reply_markup: Any = None,
    keyboard_markup: Any = None,
) -> int | None:
    try:
        if copy_from and copy_from.get("chat_id") and copy_from.get("message_id"):
            msg = await bot.copy_message(
                chat_id=chat_id,
                from_chat_id=copy_from["chat_id"],
                message_id=copy_from["message_id"],
                reply_markup=reply_markup,
            )
            return msg.message_id

        if sticker_file_id:
            msg = await bot.send_sticker(chat_id, sticker_file_id, reply_markup=reply_markup)
            return msg.message_id

        if animation_file_id:
            msg = await bot.send_animation(
                chat_id, _resolve_media(animation_file_id),
                caption=text or "", reply_markup=reply_markup,
            )
            return msg.message_id

        if video_file_id:
            msg = await bot.send_video(
                chat_id, _resolve_media(video_file_id),
                caption=text or "", reply_markup=reply_markup,
            )
            return msg.message_id

        if document_file_id:
            msg = await bot.send_document(
                chat_id, _resolve_media(document_file_id),
                caption=text or "", reply_markup=reply_markup,
            )
            return msg.message_id

        if photo_file_id:
            msg = await bot.send_photo(
                chat_id, _resolve_media(photo_file_id),
                caption=text or "", reply_markup=reply_markup,
            )
            return msg.message_id

        if keyboard_markup is not None and reply_markup is not None:
            msg = await bot.send_message(chat_id, text or "...", reply_markup=reply_markup)
            await bot.send_message(chat_id, "⌨️", reply_markup=keyboard_markup)
            return msg.message_id

        markup = reply_markup if reply_markup is not None else keyboard_markup
        msg = await bot.send_message(chat_id, text or "...", reply_markup=markup)
        return msg.message_id
    except TelegramForbiddenError:
        raise
    except Exception as e:
        log.exception("send_step_message error: %s", e)
        return None


def reply_keyboard(text: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=text)]],
        resize_keyboard=True,
        one_time_keyboard=False,
    )


def remove_keyboard() -> ReplyKeyboardRemove:
    return ReplyKeyboardRemove()


def parse_token(text: str) -> str | None:
    m = re.search(r"(\d{6,}:[A-Za-z0-9_-]{30,})", text or "")
    return m.group(1) if m else None
