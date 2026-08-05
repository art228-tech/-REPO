"""Редактор поста — собранный сам или пересланный."""
from __future__ import annotations

import json

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from database import get_db
from handlers.common import is_admin
from keyboards.kb import buttons_choice, buttons_color_choice, task_card
from states.fsm import PostStates

router = Router()


def _extract_buttons(message: Message) -> list[dict]:
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
    cfg: dict = {}
    # html_text собирает HTML из текста ИЛИ caption + entities — с премиум-эмодзи
    cfg["text"] = message.html_text or None
    if message.photo:
        cfg["photo_file_id"] = message.photo[-1].file_id
    if message.animation:
        cfg["animation_file_id"] = message.animation.file_id
    if message.video:
        cfg["video_file_id"] = message.video.file_id
    if message.document and not message.animation:
        cfg["document_file_id"] = message.document.file_id
    if message.sticker:
        import logging as _l; _l.getLogger("ap").warning("STICKER DUMP: %s", message.sticker.model_dump())
        cfg["sticker_file_id"] = message.sticker.file_id
    return cfg


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
        "• <b>перешли готовый</b> — копия 1-в-1, кнопки берутся с него;\n"
        "• <b>собери сам</b> — текст + медиа одним сообщением.\n\n"
        "Жду…"
    )
    await cb.answer()


@router.message(PostStates.wait_content)
async def m_post_content(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return
    data = await state.get_data()
    draft = data.get("draft", {})

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
        # пересланный пост: 1-в-1 + кнопки с оригинала
        draft["copy_from_chat"] = fwd_chat
        draft["copy_from_msg"] = fwd_mid
        btns = _extract_buttons(message)
        if btns:
            draft["buttons"] = json.dumps(btns, ensure_ascii=False)
        await state.update_data(draft=draft)
        await state.set_state(PostStates.wait_next_delay)
        note = f" (кнопок: {len(btns)})" if btns else ""
        await message.answer(
            f"📋 Пост-копия сохранён{note}.\n\n"
            "⏱ Через сколько секунд после этого поста публиковать следующий? "
            "Пришли число."
        )
        return

    # свой пост
    cfg = _extract_content(message)
    if not any([cfg.get(k) for k in (
        "text","photo_file_id","animation_file_id","video_file_id",
        "document_file_id","sticker_file_id"
    )]):
        await message.answer("Пустой пост. Пришли текст и/или медиа.")
        return
    draft.update(cfg)
    btns = _extract_buttons(message)
    if btns:
        draft["buttons"] = json.dumps(btns, ensure_ascii=False)
    await state.update_data(draft=draft)
    await state.set_state(PostStates.wait_buttons_choice)
    await message.answer(
        "Пост сохранён. Добавить <b>кнопки</b>?",
        reply_markup=buttons_choice(),
    )


@router.callback_query(PostStates.wait_buttons_choice, F.data == "pbtn:add")
async def cb_pbtn_add(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(PostStates.wait_button_text)
    await cb.message.edit_text("Текст кнопки:")
    await cb.answer()


@router.message(PostStates.wait_button_text)
async def m_btn_text(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.answer("Нужен текст.")
        return
    await state.update_data(_btn_text=message.text.strip())
    await state.set_state(PostStates.wait_button_url)
    await message.answer("Ссылка кнопки (https://…):")


@router.message(PostStates.wait_button_url)
async def m_btn_url(message: Message, state: FSMContext) -> None:
    url = (message.text or "").strip()
    if not (url.startswith("http://") or url.startswith("https://") or url.startswith("tg://")):
        await message.answer("Нужна корректная ссылка.")
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


# [patch4] после кнопок — спросить цвет (если кнопки есть)
async def _ask_delay(cb_or_msg) -> None:
    await cb_or_msg.edit_text(
        "⏱ Через сколько секунд после этого поста публиковать следующий? Пришли число."
    )


@router.callback_query(PostStates.wait_buttons_choice, F.data == "pbtn:done")
async def cb_pbtn_done(cb: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    draft = data.get("draft", {})
    has_buttons = False
    if draft.get("buttons"):
        try:
            has_buttons = len(json.loads(draft["buttons"])) > 0
        except Exception:
            has_buttons = False
    if has_buttons:
        await state.set_state(PostStates.wait_btn_color)
        await cb.message.edit_text(
            "🎨 <b>Цвет кнопок</b>\n\nВыбери цвет для кнопок поста:",
            reply_markup=buttons_color_choice(),
        )
        await cb.answer()
        return
    await state.set_state(PostStates.wait_next_delay)
    await _ask_delay(cb.message)
    await cb.answer()


@router.callback_query(PostStates.wait_btn_color, F.data.startswith("pcolor:"))
async def cb_pcolor(cb: CallbackQuery, state: FSMContext) -> None:
    style = cb.data.split(":")[1]  # success/danger/primary/none
    data = await state.get_data()
    draft = data.get("draft", {})
    try:
        btns = json.loads(draft["buttons"]) if draft.get("buttons") else []
    except Exception:
        btns = []
    for b in btns:
        if isinstance(b, dict) and b.get("url"):
            if style == "none":
                b.pop("style", None)
            else:
                b["style"] = style
    draft["buttons"] = json.dumps(btns, ensure_ascii=False) if btns else None
    await state.update_data(draft=draft)
    await state.set_state(PostStates.wait_next_delay)
    label = {"success": "🟢 зелёные", "danger": "🔴 красные",
             "primary": "🔵 синие", "none": "⚪ без цвета"}.get(style, style)
    await cb.message.edit_text(
        f"Цвет кнопок: {label}.\n\n"
        "⏱ Через сколько секунд после этого поста публиковать следующий? Пришли число."
    )
    await cb.answer()


@router.message(PostStates.wait_next_delay)
async def m_next_delay(message: Message, state: FSMContext) -> None:
    try:
        v = int((message.text or "").strip())
        if v < 1:
            raise ValueError
    except ValueError:
        await message.answer("Целое число секунд (1+).")
        return
    data = await state.get_data()
    draft = data["draft"]
    draft["next_delay"] = v
    await state.update_data(draft=draft)
    await state.set_state(PostStates.wait_delete_after)
    await message.answer(
        "🗑 Через сколько секунд автоматически удалить пост?\n"
        "(<b>0</b> — не удалять)"
    )


@router.message(PostStates.wait_delete_after)
async def m_delete_after(message: Message, state: FSMContext) -> None:
    try:
        v = int((message.text or "").strip())
        if v < 0:
            raise ValueError
    except ValueError:
        await message.answer("Целое число (0 или больше).")
        return
    data = await state.get_data()
    draft = data["draft"]
    task_id = data["task_id"]
    draft["delete_after"] = v

    await get_db().add_post(task_id, draft)
    await state.clear()
    task = await get_db().get_task(task_id)
    posts = await get_db().list_posts(task_id)
    await message.answer(
        f"✅ Пост добавлен.\n\n<b>📋 {task['name']}</b>\nПостов: {len(posts)}",
        reply_markup=task_card(task_id, posts),
    )
