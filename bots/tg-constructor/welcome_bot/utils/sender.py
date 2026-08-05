"""
Utility to send/copy stored messages to users via child bots.
"""
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder


def _build_keyboard(buttons_data: list | None) -> InlineKeyboardMarkup | None:
    if not buttons_data:
        return None
    builder = InlineKeyboardBuilder()
    for row in buttons_data:
        row_btns = []
        for btn in row:
            if btn.get("web_app"):
                row_btns.append(InlineKeyboardButton(
                    text=btn["text"],
                    web_app=WebAppInfo(url=btn["web_app"])
                ))
            elif btn.get("url"):
                row_btns.append(InlineKeyboardButton(text=btn["text"], url=btn["url"]))
            elif btn.get("callback_data"):
                row_btns.append(InlineKeyboardButton(text=btn["text"], callback_data=btn["callback_data"]))
        if row_btns:
            builder.row(*row_btns)
    return builder.as_markup()


async def send_stored_message(bot: Bot, chat_id: int, msg_data: dict) -> int | None:
    """
    Send a message based on stored message_data dict.
    Returns sent message_id or None.
    """
    if not msg_data:
        return None

    content_type = msg_data.get("content_type", "text")
    kb = _build_keyboard(msg_data.get("buttons"))
    file_id = msg_data.get("file_id")
    text = msg_data.get("text", "")
    caption = msg_data.get("caption", "")

    sent = None

    if content_type == "text":
        sent = await bot.send_message(chat_id, text or ".", reply_markup=kb, parse_mode="HTML")
    elif content_type == "photo":
        sent = await bot.send_photo(chat_id, file_id, caption=caption or None,
                                     reply_markup=kb, parse_mode="HTML")
    elif content_type == "video":
        sent = await bot.send_video(chat_id, file_id, caption=caption or None,
                                     reply_markup=kb, parse_mode="HTML")
    elif content_type == "document":
        sent = await bot.send_document(chat_id, file_id, caption=caption or None,
                                        reply_markup=kb, parse_mode="HTML")
    elif content_type == "sticker":
        sent = await bot.send_sticker(chat_id, file_id, reply_markup=kb)
    elif content_type == "animation":
        sent = await bot.send_animation(chat_id, file_id, caption=caption or None,
                                         reply_markup=kb, parse_mode="HTML")
    elif content_type == "voice":
        sent = await bot.send_voice(chat_id, file_id, caption=caption or None,
                                     reply_markup=kb, parse_mode="HTML")
    elif content_type == "audio":
        sent = await bot.send_audio(chat_id, file_id, caption=caption or None,
                                     reply_markup=kb, parse_mode="HTML")
    else:
        sent = await bot.send_message(chat_id, text or caption or "📩", reply_markup=kb, parse_mode="HTML")

    return sent.message_id if sent else None


async def delete_messages(bot: Bot, chat_id: int, message_ids: list[int]):
    """Delete a list of message IDs, ignoring errors."""
    for mid in message_ids:
        try:
            await bot.delete_message(chat_id, mid)
        except Exception:
            pass
