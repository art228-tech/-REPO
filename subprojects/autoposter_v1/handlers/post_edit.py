"""Редактор поста: контент (свой или пересылка), кнопки, интервалы."""
from __future__ import annotations

import json

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from database import get_db
from handlers.common import is_admin
from keyboards.kb import buttons_choice, task_card
from states.fsm import PostStates
from utils.helpers import post_summary

router = Router()


def _extract_buttons(message: Message) -> list[dict]:
    """Достаёт кнопки-ссылки из reply_markup сообщения."""
    out = []
    rm = message.reply_markup
    if rm and getattr(rm, "inline_keyboard", None):
        for row in rm.inline_keyboard:
            for b in row:
                if b.url:
                    btn = {"text": b.text, "url": b.url}
                    st = getattr(b, "style", None)
                    if st:
                        btn["style"] = st
                    em = getattr(b, "icon_custom_emoji_id", None)
                    if em:
                        btn["icon_custom_emoji_id"] = em
                    out.append(btn)
    return out


def _extract_content(message: Message) -> dict:
    """Контент собственного поста — текст (с HTML-форматированием) и медиа."""
    cfg: dict = {}
    # текст/подпись в HTML, чтобы сохранить форматирование и премиум-эмодзи
    html = None
    if message.html_text:
        html = message.html_text
    elif message.caption:
        html = message.caption
    cfg["text"] = html
    if message.photo:
        cfg["photo_file_id"] = message.photo[-1].file_id
    if message.animation:
        cfg["animation_file_id"] = message.animation.file_id
    if message.video:
        cfg["video_file_id"] = message.video.file_id
    if message.document and not message.animation:
        cfg["document_file_id"] = message.document.file_id
    if message.sticker:
        cfg["sticker_file_id"] = message.sticker.file_id
    return cfg


# ===== Старт добавления поста =====
@router.callback_query(F.data.startswith("post_add:"))
async def cb_post_add(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        return
    task_id = int(cb.data.split(":")[1])
    await state.set_state(PostStates.wait_content)
    await state.update_data(task_id=task_id, draft={})
    await cb.message.edit_text(
        "<b>➕ Новый пост</b>\n\n"
        "Пришли пост одним из способов:\n"
        "• <b>перешли готовый пост</b> — скопируется 1-в-1, кнопки с него возьмутся;\n"
        "• <b>набери сам</b> — текст с форматированием + медиа одним сообщением.\n\n"
        "Жду сообщение…"
    )
    await cb.answer()


@router.message(PostStates.wait_content)
async def m_post_content(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return
    data = await state.get_data()
    draft = data.get("draft", {})

    # переслано из канала/чата/бота?
    origin = getattr(message, "forward_origin", None)
    fwd_chat = None
    fwd_mid = None
    if origin is not None:
        och = getattr(origin, "chat", None)
        omid = getattr(origin, "message_id", None)
        if och is not None and omid is not None:
            fwd_chat, fwd_mid = och.id, omid
    if fwd_chat is None and message.forward_from_chat and message.forward_from_message_id:
        fwd_chat = message.forward_from_chat.id
        fwd_mid = message.forward_from_message_id

    if fwd_chat is not None:
        # ПЕРЕСЛАННЫЙ ПОСТ — копия 1-в-1, кнопки берём с него
        draft["copy_from_chat"] = fwd_chat
        draft["copy_from_msg"] = fwd_mid
        btns = _extract_buttons(message)
        if btns:
            draft["buttons"] = json.dumps(btns, ensure_ascii=False)
        await state.update_data(draft=draft)
        # кнопки уже взяты — сразу к интервалу
        await state.set_state(PostStates.wait_next_delay)
        note = f" (кнопок взято: {len(btns)})" if btns else ""
        await message.answer(
            f"📋 Пост-копия сохранён{note}.\n\n"
            "⏱ Через сколько <b>секунд</b> после этого поста публиковать следующий? "
            "Пришли число."
        )
        return

    # СВОЙ ПОСТ — собираем контент
    cfg = _extract_content(message)
    if not any([cfg.get("text"), cfg.get("photo_file_id"), cfg.get("animation_file_id"),
                cfg.get("video_file_id"), cfg.get("document_file_id"),
                cfg.get("sticker_file_id")]):
        await message.answer("Пустой пост. Пришли текст и/или медиа.")
        return
    draft.update(cfg)
    # переносим кнопки если вдруг были (своё сообщение с кнопками — редко, но ок)
    btns = _extract_buttons(message)
    if btns:
        draft["buttons"] = json.dumps(btns, ensure_ascii=False)
    await state.update_data(draft=draft)
    await state.set_state(PostStates.wait_buttons_choice)
    await message.answer(
        "Пост сохранён. Добавить <b>кнопки</b>?",
        reply_markup=buttons_choice(),
    )


# ===== Кнопки своего поста =====
@router.callback_query(PostStates.wait_buttons_choice, F.data == "pbtn:add")
async def cb_pbtn_add(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(PostStates.wait_button_text)
    await cb.message.edit_text("Пришли <b>текст кнопки</b>:")
    await cb.answer()


@router.message(PostStates.wait_button_text)
async def m_btn_text(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.answer("Нужен текст.")
        return
    await state.update_data(_btn_text=message.text.strip())
    await state.set_state(PostStates.wait_button_url)
    await message.answer("Пришли <b>ссылку</b> для кнопки (https://…):")


@router.message(PostStates.wait_button_url)
async def m_btn_url(message: Message, state: FSMContext) -> None:
    url = (message.text or "").strip()
    if not (url.startswith("http://") or url.startswith("https://") or url.startswith("tg://")):
        await message.answer("Нужна корректная ссылка (http/https).")
        return
    data = await state.get_data()
    draft = data["draft"]
    btns = json.loads(draft["buttons"]) if draft.get("buttons") else []
    btns.append({"text": data["_btn_text"], "url": url})
    draft["buttons"] = json.dumps(btns, ensure_ascii=False)
    await state.update_data(draft=draft)
    await state.set_state(PostStates.wait_buttons_choice)
    await message.answer(
        f"Кнопка добавлена (всего: {len(btns)}). Ещё одну или закончить?",
        reply_markup=buttons_choice(),
    )


@router.callback_query(PostStates.wait_buttons_choice, F.data == "pbtn:done")
async def cb_pbtn_done(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(PostStates.wait_next_delay)
    await cb.message.edit_text(
        "⏱ Через сколько <b>секунд</b> после этого поста публиковать следующий? "
        "Пришли число."
    )
    await cb.answer()


# ===== Интервал =====
@router.message(PostStates.wait_next_delay)
async def m_next_delay(message: Message, state: FSMContext) -> None:
    try:
        v = int((message.text or "").strip())
        if v < 1:
            raise ValueError
    except ValueError:
        await message.answer("Нужно целое число секунд (1 или больше).")
        return
    data = await state.get_data()
    draft = data["draft"]
    draft["next_delay"] = v
    await state.update_data(draft=draft)
    await state.set_state(PostStates.wait_delete_after)
    await message.answer(
        "🗑 Через сколько <b>секунд</b> автоматически удалить этот пост?\n"
        "Пришли число (<b>0</b> — не удалять)."
    )


# ===== Автоудаление + сохранение =====
@router.message(PostStates.wait_delete_after)
async def m_delete_after(message: Message, state: FSMContext) -> None:
    try:
        v = int((message.text or "").strip())
        if v < 0:
            raise ValueError
    except ValueError:
        await message.answer("Нужно целое число (0 или больше).")
        return
    data = await state.get_data()
    draft = data["draft"]
    task_id = data["task_id"]
    draft["delete_after"] = v

    await get_db().add_post(task_id, draft)
    await state.clear()

    db = get_db()
    task = await db.get_task(task_id)
    posts = await db.list_posts(task_id)
    await message.answer(
        f"✅ Пост добавлен.\n\n<b>📋 {task['name']}</b>\nПостов: {len(posts)}",
        reply_markup=task_card(task_id, posts),
    )
