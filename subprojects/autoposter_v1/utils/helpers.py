"""Хелперы автопостера: сборка кнопок, отправка постов."""
from __future__ import annotations

import json
from typing import Any, Optional

from aiogram import Bot
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LinkPreviewOptions,
)


def build_keyboard(buttons_raw: Any) -> Optional[InlineKeyboardMarkup]:
    """Строит inline-клавиатуру из сохранённого JSON.
    Формат каждой кнопки: {text, url, style?, icon_custom_emoji_id?}.
    Раскладка — по 1 в ряд (просто и предсказуемо для постов).
    """
    if not buttons_raw:
        return None
    if isinstance(buttons_raw, str):
        try:
            buttons = json.loads(buttons_raw)
        except Exception:
            return None
    else:
        buttons = buttons_raw
    if not buttons:
        return None

    rows = []
    for b in buttons:
        if not isinstance(b, dict) or not b.get("url"):
            continue
        kwargs: dict = {"text": b.get("text", "Кнопка"), "url": b["url"]}
        if b.get("style"):
            kwargs["style"] = b["style"]
        if b.get("icon_custom_emoji_id"):
            kwargs["icon_custom_emoji_id"] = b["icon_custom_emoji_id"]
        try:
            rows.append([InlineKeyboardButton(**kwargs)])
        except TypeError:
            kwargs.pop("style", None)
            kwargs.pop("icon_custom_emoji_id", None)
            rows.append([InlineKeyboardButton(**kwargs)])
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


async def send_post(bot: Bot, chat_id: int, post) -> Optional[int]:
    """Отправляет пост в канал. Возвращает message_id или None.
    post — sqlite3.Row из таблицы posts.
    """
    markup = build_keyboard(post["buttons"])

    # Пост-копия: 1-в-1 через copy_message
    if post["copy_from_chat"] and post["copy_from_msg"]:
        msg = await bot.copy_message(
            chat_id=chat_id,
            from_chat_id=post["copy_from_chat"],
            message_id=post["copy_from_msg"],
            reply_markup=markup,
        )
        return msg.message_id

    text = post["text"] or ""

    if post["sticker_file_id"]:
        msg = await bot.send_sticker(chat_id, post["sticker_file_id"], reply_markup=markup)
        return msg.message_id
    if post["animation_file_id"]:
        msg = await bot.send_animation(
            chat_id, post["animation_file_id"], caption=text or None, reply_markup=markup
        )
        return msg.message_id
    if post["video_file_id"]:
        msg = await bot.send_video(
            chat_id, post["video_file_id"], caption=text or None, reply_markup=markup
        )
        return msg.message_id
    if post["document_file_id"]:
        msg = await bot.send_document(
            chat_id, post["document_file_id"], caption=text or None, reply_markup=markup
        )
        return msg.message_id
    if post["photo_file_id"]:
        msg = await bot.send_photo(
            chat_id, post["photo_file_id"], caption=text or None, reply_markup=markup
        )
        return msg.message_id

    # просто текст
    msg = await bot.send_message(
        chat_id, text or "...", reply_markup=markup,
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )
    return msg.message_id


def post_summary(post, idx: int) -> str:
    """Краткое описание поста для карточки."""
    parts = [f"<b>Пост {idx}</b>"]
    if post["copy_from_chat"]:
        parts.append("📋 Копия пересланного поста")
    else:
        kind = []
        if post["photo_file_id"]:
            kind.append("фото")
        if post["animation_file_id"]:
            kind.append("гиф")
        if post["video_file_id"]:
            kind.append("видео")
        if post["sticker_file_id"]:
            kind.append("стикер")
        if post["document_file_id"]:
            kind.append("файл")
        if post["text"]:
            kind.append("текст")
        parts.append("Контент: " + (", ".join(kind) if kind else "—"))
    try:
        nb = len(json.loads(post["buttons"])) if post["buttons"] else 0
    except Exception:
        nb = 0
    parts.append(f"Кнопок: {nb}")
    parts.append(f"⏱ Через {post['next_delay']} с — следующий пост")
    if post["delete_after"]:
        parts.append(f"🗑 Удаление через {post['delete_after']} с")
    else:
        parts.append("🗑 Не удалять")
    return "\n".join(parts)
