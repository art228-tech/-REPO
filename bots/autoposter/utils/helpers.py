"""Хелперы: сборка inline-клавиатуры, отправка постов через помощника."""
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
    """Inline-клавиатура из JSON. Поддерживает style и icon_custom_emoji_id."""
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
        # [patch3] цвет кнопки: success(зелёная)/danger(красная)/primary(синяя)
        _style = b.get("style")
        if _style in ("primary", "success", "danger"):
            kwargs["style"] = _style
        try:
            btn = InlineKeyboardButton(**kwargs)
        except TypeError:
            # на случай очень старой aiogram без поля style — деградируем без цвета
            kwargs.pop("style", None)
            btn = InlineKeyboardButton(**kwargs)
        em = b.get("icon_custom_emoji_id")
        if em:
            try:
                object.__setattr__(btn, "icon_custom_emoji_id", em)
            except Exception:
                pass
        rows.append([btn])
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


async def send_post(bot: Bot, chat_id: int, post) -> Optional[int]:
    """Отправляет пост в канал от имени переданного бота."""
    markup = build_keyboard(post["buttons"])

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
            chat_id, await _ap_media(post, "animation_bytes", "animation_file_id", "a.gif"),
            caption=text or None, reply_markup=markup,
        )
        return msg.message_id
    if post["video_file_id"]:
        msg = await bot.send_video(
            chat_id, await _ap_media(post, "video_bytes", "video_file_id", "v.mp4"),
            caption=text or None, reply_markup=markup,
        )
        return msg.message_id
    if post["document_file_id"]:
        msg = await bot.send_document(
            chat_id, await _ap_media(post, "document_bytes", "document_file_id", "file.bin"),
            caption=text or None, reply_markup=markup,
        )
        return msg.message_id
    if post["photo_file_id"]:
        msg = await bot.send_photo(
            chat_id, await _ap_media(post, "photo_bytes", "photo_file_id", "p.jpg"),
            caption=text or None, reply_markup=markup,
        )
        import logging as _l
        _ce = [e.type for e in (msg.caption_entities or [])]
        _l.getLogger("ap").warning("SENT PHOTO caption_entities=%s caption=%r", _ce, (msg.caption or "")[:60])
        return msg.message_id

    msg = await bot.send_message(
        chat_id, text or "...", reply_markup=markup,
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )
    return msg.message_id


def post_summary(post, idx: int) -> str:
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


# === [patch2] медиа из байтов или file_id, с автодоливом байтов ===
import os as _os
import sqlite3 as _sqlite3

from aiogram.types import BufferedInputFile as _BufferedInputFile

_AP_DB = _os.getenv("DB_PATH", "/opt/autoposter/data.db")


def _ap_bot_token() -> str:
    t = _os.getenv("BOT_TOKEN", "").strip()
    if t:
        return t
    try:
        for ln in open("/opt/autoposter/.env", encoding="utf-8"):
            ln = ln.strip()
            if ln.startswith("BOT_TOKEN="):
                return ln.split("=", 1)[1].strip()
    except Exception:
        pass
    return ""


async def _ap_backfill_bytes(post, fid: str, bcol: str) -> bytes | None:
    """Скачивает файл основным ботом и сохраняет байты в БД (один раз на пост)."""
    from aiogram import Bot as _Bot
    token = _ap_bot_token()
    if not token or not fid:
        return None
    try:
        b = _Bot(token)
        f = await b.get_file(fid)
        buf = await b.download_file(f.file_path)
        data = buf.read()
        await b.session.close()
        try:
            conn = _sqlite3.connect(_AP_DB)
            conn.execute(f"UPDATE posts SET {bcol}=? WHERE id=?", (data, post["id"]))
            conn.commit()
            conn.close()
        except Exception:
            pass
        return data
    except Exception:
        return None


async def _ap_media(post, bcol: str, fcol: str, filename: str):
    """Возвращает BufferedInputFile (байты) либо file_id; доливает байты при нужде."""
    data = None
    try:
        data = post[bcol]
    except (KeyError, IndexError, TypeError):
        data = None
    if not data:
        fid = None
        try:
            fid = post[fcol]
        except (KeyError, IndexError, TypeError):
            fid = None
        if fid:
            data = await _ap_backfill_bytes(post, fid, bcol)
            if not data:
                return fid  # последний шанс — старый путь
    if data:
        return _BufferedInputFile(data, filename=filename)
    return None
# === [/patch2] ===
