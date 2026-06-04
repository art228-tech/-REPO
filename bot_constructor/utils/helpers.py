"""Хелперы: цвета кнопок, рендер сообщений, парсинг."""
from __future__ import annotations

import logging
import os
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import (
    LinkPreviewOptions,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
    FSInputFile,
)

log = logging.getLogger("helpers")


class CopyOriginGone(Exception):
    """Оригинал скопированного поста удалён/недоступен (патч 26)."""


# Цвета кнопок в Telegram реализуются через WebApp/Login/SwitchInline и т.п.
# В обычных inline-кнопках Telegram не позволяет менять цвет произвольно.
# Однако через "обычный" режим бота при использовании cmds @reply Telegram
# отображает зелёный/красный фон для некоторых типов. Мы реализуем "цвета"
# с помощью эмодзи-маркеров в начале текста кнопки — это привычная и
# наиболее распространённая в Telegram-сценариях практика.
COLOR_PREFIXES = {
    "default": "",
    "blue":    "🔹 ",
    "green":   "🟢 ",
    "red":     "🔴 ",
    "yellow":  "🟡 ",
    "purple":  "🟣 ",
    "orange":  "🟠 ",
    "white":   "⚪ ",
    "black":   "⚫ ",
    "fire":    "🔥 ",
    "star":    "⭐ ",
    "heart":   "❤️ ",
    "rocket":  "🚀 ",
    "lock":    "🔒 ",
    "key":     "🔑 ",
    "check":   "✅ ",
    "cross":   "❌ ",
    "gift":    "🎁 ",
}

COLOR_LABELS = {
    "default": "Без префикса",
    "blue":    "🔹 Синяя",
    "green":   "🟢 Зелёная",
    "red":     "🔴 Красная",
    "yellow":  "🟡 Жёлтая",
    "purple":  "🟣 Фиолетовая",
    "orange":  "🟠 Оранжевая",
    "white":   "⚪ Белая",
    "black":   "⚫ Чёрная",
    "fire":    "🔥 Огонь",
    "star":    "⭐ Звезда",
    "heart":   "❤️ Сердце",
    "rocket":  "🚀 Ракета",
    "lock":    "🔒 Замок",
    "key":     "🔑 Ключ",
    "check":   "✅ Галка",
    "cross":   "❌ Крест",
    "gift":    "🎁 Подарок",
}

# Псевдоним для нативных цветов кнопок (используется в sponsor_edit, патч 6/13)
STYLE_LABELS = COLOR_LABELS


def color_button_text(text: str, color: str = "default") -> str:
    return COLOR_PREFIXES.get(color, "") + text


def build_inline_keyboard(rows: list[list[dict[str, Any]]]) -> InlineKeyboardMarkup | None:
    """rows — список рядов кнопок. Каждая кнопка — dict с ключами text, url|callback_data|web_app, color."""
    if not rows:
        return None
    built: list[list[InlineKeyboardButton]] = []
    for row in rows:
        line: list[InlineKeyboardButton] = []
        for btn in row:
            text = color_button_text(btn.get("text", "Кнопка"), btn.get("color", "default"))
            kwargs: dict[str, Any] = {"text": text}
            if btn.get("url"):
                kwargs["url"] = btn["url"]
            elif btn.get("callback_data"):
                kwargs["callback_data"] = btn["callback_data"]
            elif btn.get("web_app"):
                from aiogram.types import WebAppInfo
                kwargs["web_app"] = WebAppInfo(url=btn["web_app"])
            else:
                continue
            # Нативный цвет (Bot API 9.4) и премиум-стикер.
            # Передаём через kwargs — если поле не поддерживается, отлавливаем.
            if btn.get("style"):
                kwargs["style"] = btn["style"]
            if btn.get("icon_custom_emoji_id"):
                kwargs["icon_custom_emoji_id"] = btn["icon_custom_emoji_id"]
            try:
                line.append(InlineKeyboardButton(**kwargs))
            except TypeError:
                # старый aiogram без style/icon — убираем эти поля
                kwargs.pop("style", None)
                kwargs.pop("icon_custom_emoji_id", None)
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
    copy_from: dict | None = None,  # {chat_id, message_id}
    reply_markup: Any = None,
    keyboard_markup: Any = None,  # ReplyKeyboardMarkup
    photo_path: str | None = None,  # локальный файл фото (file_id не переносится между ботами)
) -> int | None:
    """
    Отправляет сообщение в зависимости от типа контента.
    Возвращает message_id отправленного сообщения, либо None при ошибке.
    """
    try:
        # Если указан copy_from (переслать пост из чата) — копируем
        if copy_from and copy_from.get("chat_id") and copy_from.get("message_id"):
            try:
                msg = await bot.copy_message(
                    chat_id=chat_id,
                    from_chat_id=copy_from["chat_id"],
                    message_id=copy_from["message_id"],
                    reply_markup=reply_markup,
                )
            except TelegramBadRequest as _e:
                if "message to copy not found" in str(_e).lower():
                    raise CopyOriginGone()
                raise
            return msg.message_id

        if sticker_file_id:
            msg = await bot.send_sticker(chat_id, sticker_file_id, reply_markup=reply_markup)
            return msg.message_id

        if animation_file_id:
            msg = await bot.send_animation(
                chat_id, animation_file_id, caption=text or "", reply_markup=reply_markup
            )
            return msg.message_id

        if video_file_id:
            msg = await bot.send_video(
                chat_id, video_file_id, caption=text or "", reply_markup=reply_markup
            )
            return msg.message_id

        if document_file_id:
            msg = await bot.send_document(
                chat_id, document_file_id, caption=text or "", reply_markup=reply_markup
            )
            return msg.message_id

        if photo_path and os.path.exists(photo_path):
            # file_id, полученный конструктором, нельзя переслать через приветку
            # (file_id привязан к боту). Поэтому шлём фото как локальный файл.
            msg = await bot.send_photo(
                chat_id, FSInputFile(photo_path), caption=text or "", reply_markup=reply_markup
            )
            return msg.message_id

        if photo_file_id:
            msg = await bot.send_photo(
                chat_id, photo_file_id, caption=text or "", reply_markup=reply_markup
            )
            return msg.message_id

        # Просто текст; если ещё нужно показать reply keyboard — делаем отдельным сообщением
        if keyboard_markup is not None and reply_markup is not None:
            msg = await bot.send_message(
                chat_id, text or "...", reply_markup=reply_markup,
                link_preview_options=LinkPreviewOptions(is_disabled=True),
            )
            # Reply keyboard приходит через отдельное сообщение
            await bot.send_message(chat_id, "⌨️", reply_markup=keyboard_markup)
            return msg.message_id

        markup = reply_markup if reply_markup is not None else keyboard_markup
        msg = await bot.send_message(
            chat_id, text or "...", reply_markup=markup,
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )
        return msg.message_id
    except TelegramForbiddenError:
        raise  # пробрасываем выше — юзер заблокировал
    except Exception as e:
        log.warning("send_step_message error (chat %s): %s", chat_id, e)
        return None


async def rehost_step_photos(bot: Bot, media_dir: str) -> int:
    """Скачивает фото шагов (photo_file_id конструктора) на диск и проставляет
    cfg['photo_path']. file_id привязан к боту-конструктору и не работает у
    приветок — поэтому фото надо отправлять как локальный файл (FSInputFile)."""
    import json
    from database import get_db

    os.makedirs(media_dir, exist_ok=True)
    db = get_db()
    cur = await db.conn.execute("SELECT id, config FROM steps")
    rows = await cur.fetchall()
    fixed = 0
    for r in rows:
        sid, cfg_raw = r[0], r[1]
        try:
            cfg = json.loads(cfg_raw)
        except Exception:
            continue
        fid = cfg.get("photo_file_id")
        if not fid:
            continue
        path = cfg.get("photo_path")
        if path and os.path.exists(path):
            continue
        dest = os.path.join(media_dir, f"step_{sid}.jpg")
        try:
            await bot.download(fid, destination=dest)
        except Exception as e:
            log.warning("rehost_step_photos: шаг %s — %s", sid, e)
            continue
        cfg["photo_path"] = dest
        await db.update_step(sid, config=json.dumps(cfg, ensure_ascii=False))
        fixed += 1
    if fixed:
        log.info("rehost_step_photos: перезалито фото шагов: %s", fixed)
    return fixed


def reply_keyboard(text: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=text)]],
        resize_keyboard=True,
        one_time_keyboard=False,
    )


def remove_keyboard() -> ReplyKeyboardRemove:
    return ReplyKeyboardRemove()


def parse_token(text: str) -> str | None:
    """Извлекает токен бота из строки. Формат: цифры:буквы-цифры-знаки."""
    import re
    m = re.search(r"(\d{6,12}):([A-Za-z0-9_-]{30,})", text)
    if m:
        return f"{m.group(1)}:{m.group(2)}"
    return None


def fmt_seconds(s: int) -> str:
    if s < 60:
        return f"{s} с"
    if s < 3600:
        return f"{s // 60} мин {s % 60} с" if s % 60 else f"{s // 60} мин"
    h, rest = divmod(s, 3600)
    m, sec = divmod(rest, 60)
    parts = [f"{h} ч"]
    if m:
        parts.append(f"{m} мин")
    if sec:
        parts.append(f"{sec} с")
    return " ".join(parts)


def extract_first_custom_emoji_id(html_text: str):
    """Достаёт id первого custom-emoji из HTML-текста, или None."""
    if not html_text:
        return None
    import re
    m = re.search(r'<tg-emoji\s+emoji-id="(\d+)"', html_text)
    return m.group(1) if m else None


def strip_custom_emoji(html_text: str) -> str:
    """Убирает теги <tg-emoji> из текста, оставляя содержимое."""
    if not html_text:
        return ""
    import re
    return re.sub(r'<tg-emoji[^>]*>(.*?)</tg-emoji>', r'\1', html_text)
