"""
Создание шагов сценария: рулетка, ОП, сообщение.

Каждый тип — это последовательная "анкета": конструктор задаёт вопросы,
пользователь отвечает, в конце шаг сохраняется в БД.
"""
from __future__ import annotations

import json
from typing import Any

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from database import get_db
from handlers.start import is_admin
from keyboards.constructor_kb import (
    add_button_now_kb,
    add_sponsor_now_kb,
    back_to,
    color_picker,
    msg_wait_mode_kb,
    scenario_menu,
    sponsor_check_kb,
)
from states.fsm import StepStates
from utils.sponsor_check import check_sponsor_access

router = Router(name="step_create")


# ---------------- Утилиты ----------------

def _extract_content(message: Message) -> dict[str, Any]:
    """Извлекает контент из сообщения. Поддерживает: фото, стикер, гифку, видео,
    документ, копию-поста (forward), просто текст."""
    cfg: dict[str, Any] = {}
    if message.photo:
        cfg["photo_file_id"] = message.photo[-1].file_id
        cfg["text"] = message.html_text or message.caption_html or ""
    elif message.sticker:
        cfg["sticker_file_id"] = message.sticker.file_id
    elif message.animation:
        cfg["animation_file_id"] = message.animation.file_id
        cfg["text"] = message.html_text or message.caption_html or ""
    elif message.video:
        cfg["video_file_id"] = message.video.file_id
        cfg["text"] = message.html_text or message.caption_html or ""
    elif message.document:
        cfg["document_file_id"] = message.document.file_id
        cfg["text"] = message.html_text or message.caption_html or ""
    elif message.text:
        cfg["text"] = message.html_text
    # Если это пересланное (forward) — сохраняем copy_from
    # Telegram отдаёт данные о пересылке либо в старом forward_from_chat,
    # --- Кнопки-ссылки извлекаем ВСЕГДА (переслано сообщение или нет) ---
    if message.reply_markup and getattr(message.reply_markup, "inline_keyboard", None):
        orig_btns = []
        for row in message.reply_markup.inline_keyboard:
            line = []
            for b in row:
                if b.url:
                    btn = {"text": b.text, "url": b.url}
                    # Нативный цвет кнопки (Bot API 9.4)
                    _style = getattr(b, "style", None)
                    if _style:
                        btn["style"] = _style
                    # Премиум-стикер на кнопке
                    _emoji = getattr(b, "icon_custom_emoji_id", None)
                    if _emoji:
                        btn["icon_custom_emoji_id"] = _emoji
                    line.append(btn)
                # callback_data-кнопки чужого бота пропускаем — не переносимы
            if line:
                orig_btns.append(line)
        if orig_btns:
            cfg["_orig_buttons"] = orig_btns

    # --- copy_from только для пересылок из КАНАЛА ---
    fwd_chat = None
    fwd_mid = None
    if message.forward_from_chat and message.forward_from_message_id:
        # старый API
        if getattr(message.forward_from_chat, "type", None) == "channel":
            fwd_chat = message.forward_from_chat.id
            fwd_mid = message.forward_from_message_id
    else:
        origin = getattr(message, "forward_origin", None)
        if origin is not None and getattr(origin, "type", None) == "channel":
            och = getattr(origin, "chat", None)
            omid = getattr(origin, "message_id", None)
            if och is not None and omid is not None:
                fwd_chat = och.id
                fwd_mid = omid
    if fwd_chat is not None and fwd_mid is not None:
        cfg["copy_from"] = {"chat_id": fwd_chat, "message_id": fwd_mid}
        # при копировании поста из канала контент берём из самого поста
        for k in ("photo_file_id", "sticker_file_id", "animation_file_id",
                  "video_file_id", "document_file_id", "text"):
            cfg.pop(k, None)
    # Если переслано от пользователя/бота (не канал) — copy_from НЕ ставим,
    # контент (текст+медиа) уже сохранён выше как обычное сообщение.
    return cfg


# ============================================================================
# СОЗДАНИЕ ШАГА — выбор типа
# ============================================================================

@router.callback_query(F.data.startswith("newstep:"))
async def cb_newstep(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        await cb.answer("⛔", show_alert=True)
        return
    _, bot_id, step_type = cb.data.split(":")
    bot_id = int(bot_id)
    await state.update_data(bot_id=bot_id, step_type=step_type, draft={})

    if step_type == "roulette":
        await state.set_state(StepStates.roulette_content)
        await cb.message.edit_text(
            "<b>🎰 Шаг: Рулетка</b>\n\n"
            "Пришли <b>текст</b> сообщения. Можно с <b>фото</b>, форматированием, "
            "эмодзи и премиум-стикерами.\n\n"
            "Например:\n"
            "<i>«🎉 Поздравляем! Тебе выпала возможность крутануть колесо фортуны "
            "и забрать главный приз — 5000 ⭐️! Жми кнопку ниже!»</i>",
            reply_markup=back_to(f"scn:{bot_id}", "❌ Отмена"),
        )
    elif step_type == "op":
        await state.set_state(StepStates.op_content)
        await cb.message.edit_text(
            "<b>📢 Шаг: Обязательная подписка</b>\n\n"
            "Пришли <b>текст</b> сообщения. Можно с <b>фото</b>.\n\n"
            "Пример:\n"
            "<i>«Чтобы продолжить, подпишись на наших партнёров 👇»</i>",
            reply_markup=back_to(f"scn:{bot_id}", "❌ Отмена"),
        )
    elif step_type == "message":
        await state.set_state(StepStates.msg_content)
        await cb.message.edit_text(
            "<b>💬 Шаг: Сообщение</b>\n\n"
            "Пришли контент сообщения. Можно:\n"
            "• Просто текст (с любым форматированием, эмодзи, премиум-стикерами)\n"
            "• Фото / гифка / стикер / видео / документ с подписью\n"
            "• <b>Пересланный пост из другого чата</b> — он будет скопирован",
            reply_markup=back_to(f"scn:{bot_id}", "❌ Отмена"),
        )
    else:
        await cb.answer("Неизвестный тип", show_alert=True)
        return
    await cb.answer()


# ============================================================================
# РУЛЕТКА
# ============================================================================

@router.message(StepStates.roulette_content)
async def m_roulette_content(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return
    data = await state.get_data()
    draft = data.get("draft", {})
    extracted = _extract_content(message)
    if not extracted.get("text") and not extracted.get("photo_file_id"):
        await message.answer("Нужен хотя бы текст. Пришли ещё раз.")
        return
    draft.update(extracted)
    await state.update_data(draft=draft)
    await state.set_state(StepStates.roulette_button_text)
    await message.answer(
        "✅ Текст принят.\n\n"
        "Теперь пришли <b>текст кнопки</b> для запуска рулетки.\n"
        "Например: <code>Крутить!</code>",
    )


@router.message(StepStates.roulette_button_text)
async def m_roulette_button(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.answer("Нужен текст (без фото). Пришли ещё раз.")
        return
    data = await state.get_data()
    draft = data["draft"]
    draft["button_text"] = message.text
    await state.update_data(draft=draft)
    await state.set_state(StepStates.roulette_button_color)
    await message.answer(
        "✅ Текст кнопки принят.\n\n"
        "Выбери <b>цвет/префикс</b> кнопки крутить рулетку:",
        reply_markup=color_picker("rclr"),
    )


@router.callback_query(StepStates.roulette_button_color, F.data.startswith("rclr:"))
async def cb_roulette_color(cb: CallbackQuery, state: FSMContext) -> None:
    color = cb.data.split(":")[1]
    data = await state.get_data()
    draft = data["draft"]
    draft["button_color"] = color
    await state.update_data(draft=draft)
    await state.set_state(StepStates.roulette_duplicate_after)
    await cb.message.edit_text(
        "✅ Цвет принят.\n\n"
        "⏱ <b>Время между дублями</b>: через сколько секунд писать "
        "юзеру повторно, если он не нажмёт кнопку?\n"
        "Пришли число секунд (например <code>60</code>)."
    )
    await cb.answer()


@router.message(StepStates.roulette_duplicate_after)
async def m_roulette_dup_after(message: Message, state: FSMContext) -> None:
    try:
        v = int(message.text.strip())
        if v < 1:
            raise ValueError
    except (ValueError, AttributeError):
        await message.answer("Нужно положительное целое число.")
        return
    data = await state.get_data()
    draft = data["draft"]
    draft["duplicate_after"] = v
    await state.update_data(draft=draft)
    await state.set_state(StepStates.roulette_duplicate_increment)
    await message.answer(
        "✅ Принято.\n\n"
        "📈 <b>Прирост</b>: насколько увеличивать интервал с каждым следующим дублем "
        "(0 — не увеличивать). Пришли число."
    )


@router.message(StepStates.roulette_duplicate_increment)
async def m_roulette_dup_inc(message: Message, state: FSMContext) -> None:
    try:
        v = int(message.text.strip())
        if v < 0:
            raise ValueError
    except (ValueError, AttributeError):
        await message.answer("Нужно неотрицательное целое.")
        return
    data = await state.get_data()
    draft = data["draft"]
    draft["duplicate_increment"] = v
    await state.update_data(draft=draft)
    await state.set_state(StepStates.roulette_duplicate_max)
    await message.answer(
        "✅ Принято.\n\n"
        "🔁 <b>Макс. число дублей</b>: сколько раз дублировать, "
        "после чего пропустить шаг. Пришли число (например <code>5</code>)."
    )


@router.message(StepStates.roulette_duplicate_max)
async def m_roulette_dup_max(message: Message, state: FSMContext) -> None:
    try:
        v = int(message.text.strip())
        if v < 0:
            raise ValueError
    except (ValueError, AttributeError):
        await message.answer("Нужно неотрицательное целое.")
        return
    data = await state.get_data()
    draft = data["draft"]
    bot_id = int(data["bot_id"])

    cfg = {
        "text": draft.get("text") or "",
        "photo_file_id": draft.get("photo_file_id"),
        "button_text": draft.get("button_text") or "🎰 Крутить рулетку",
        "button_color": draft.get("button_color") or "default",
    }
    await get_db().add_step(
        bot_id, "roulette", cfg,
        duplicate_after=draft.get("duplicate_after", 60),
        duplicate_increment=draft.get("duplicate_increment", 0),
        duplicate_max=v,
    )
    await state.clear()
    steps = await get_db().list_steps(bot_id)
    await message.answer(
        f"✅ Шаг <b>Рулетка</b> добавлен!",
        reply_markup=scenario_menu(bot_id, steps),
    )


# ============================================================================
# ОП (обязательная подписка)
# ============================================================================

@router.message(StepStates.op_content)
async def m_op_content(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    draft = data.get("draft", {})
    extracted = _extract_content(message)
    if not extracted.get("text") and not extracted.get("photo_file_id"):
        await message.answer("Нужен хотя бы текст. Пришли ещё раз.")
        return
    draft.update(extracted)
    draft.setdefault("sponsors", [])
    await state.update_data(draft=draft)
    await state.set_state(StepStates.op_add_sponsor)
    await message.answer(
        f"✅ Текст принят.\n\n"
        f"Спонсоров пока: <b>{len(draft['sponsors'])}</b>. "
        f"Добавим первого?",
        reply_markup=add_sponsor_now_kb(),
    )


@router.callback_query(StepStates.op_add_sponsor, F.data == "sp:add")
async def cb_op_sp_add(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(StepStates.op_sponsor_check)
    await cb.message.edit_text(
        "<b>Спонсор: проверять подписку?</b>\n\n"
        "✅ Если ДА — пришлёшь ID канала, бот будет проверять, "
        "подписался ли юзер. Приветку нужно сделать админом этого канала.\n\n"
        "🚫 Если НЕТ — спонсор будет просто показан в кнопках, без проверки. "
        "Юзер сможет пройти шаг без подписки на него (такие всегда показываются всем).",
        reply_markup=sponsor_check_kb(),
    )
    await cb.answer()


@router.callback_query(StepStates.op_sponsor_check, F.data.startswith("spc:"))
async def cb_op_sp_check(cb: CallbackQuery, state: FSMContext) -> None:
    is_check = cb.data.split(":")[1] == "1"
    data = await state.get_data()
    draft = data["draft"]
    draft.setdefault("_current_sponsor", {})["check"] = is_check
    await state.update_data(draft=draft)
    if is_check:
        await state.set_state(StepStates.op_sponsor_channel_id)
        await cb.message.edit_text(
            "Пришли <b>ID канала</b> (отрицательное число, например "
            "<code>-1001234567890</code>).\n\n"
            "Узнать ID можно через @username_to_id_bot или @getidsbot. "
            "Не забудь добавить приветку админом этого канала."
        )
    else:
        # без проверки — пропускаем channel_id
        draft["_current_sponsor"]["channel_id"] = 0
        await state.update_data(draft=draft)
        await state.set_state(StepStates.op_sponsor_link)
        await cb.message.edit_text(
            "Пришли <b>ссылку</b> на канал/чат спонсора (https://t.me/...)."
        )
    await cb.answer()


@router.message(StepStates.op_sponsor_channel_id)
async def m_op_sp_chan(message: Message, state: FSMContext) -> None:
    try:
        v = int(message.text.strip())
    except (ValueError, AttributeError):
        await message.answer("Нужно целое число (ID канала). Попробуй ещё раз.")
        return
    data = await state.get_data()
    draft = data["draft"]
    sp = draft["_current_sponsor"]
    sp["channel_id"] = v
    # Проверяем что приветка реально может работать с этим каналом
    from bots.manager import get_manager
    bot_id = draft.get("bot_id") or draft.get("greeting_bot_id")
    if bot_id:
        bot = get_manager().get_bot_instance(bot_id)
        if bot is not None:
            need_invite = bool(sp.get("request_mode"))
            res = await check_sponsor_access(bot, v, require_invite_users=need_invite)
            if not res["ok"]:
                hint = (
                    "<i>Канал «по заявкам» требует право «Приглашать пользователей через ссылки».</i>"
                    if need_invite else
                    "<i>Приветка должна быть админом этого канала.</i>"
                )
                await message.answer(
                    f"⚠️ <b>Не могу подключиться к каналу</b>\n\n"
                    f"Причина: {res['reason']}\n\n"
                    f"{hint}\n\n"
                    "Когда исправишь — пришли ID канала ещё раз."
                )
                return
    await state.update_data(draft=draft)
    await state.set_state(StepStates.op_sponsor_link)
    await message.answer("✅ Доступ есть.\n\nТеперь пришли <b>ссылку</b> на канал (https://t.me/...).")


@router.message(StepStates.op_sponsor_link)
async def m_op_sp_link(message: Message, state: FSMContext) -> None:
    link = (message.text or "").strip()
    if not (link.startswith("http://") or link.startswith("https://") or link.startswith("tg://")):
        await message.answer("Это не ссылка. Пришли URL вида https://t.me/...")
        return
    data = await state.get_data()
    draft = data["draft"]
    draft["_current_sponsor"]["link"] = link
    await state.update_data(draft=draft)
    await state.set_state(StepStates.op_sponsor_title)
    await message.answer("Пришли <b>название</b> спонсора (для админки).")


@router.message(StepStates.op_sponsor_title)
async def m_op_sp_title(message: Message, state: FSMContext) -> None:
    title = (message.text or "").strip()
    if not title:
        await message.answer("Пришли название.")
        return
    data = await state.get_data()
    draft = data["draft"]
    draft["_current_sponsor"]["title"] = title
    await state.update_data(draft=draft)
    await state.set_state(StepStates.op_sponsor_button_text)
    await message.answer("Пришли <b>текст кнопки</b> для этого спонсора (что будет на ней написано).")


@router.message(StepStates.op_sponsor_button_text)
async def m_op_sp_btn_text(message: Message, state: FSMContext) -> None:
    txt = (message.text or "").strip()
    if not txt:
        await message.answer("Пришли текст кнопки.")
        return
    data = await state.get_data()
    draft = data["draft"]
    draft["_current_sponsor"]["button_text"] = txt
    await state.update_data(draft=draft)
    await state.set_state(StepStates.op_sponsor_button_color)
    await message.answer(
        "Выбери <b>цвет/префикс</b> кнопки этого спонсора:",
        reply_markup=color_picker("spclr"),
    )


async def _finish_op_sponsor(target, state: FSMContext) -> None:
    data = await state.get_data()
    draft = data["draft"]
    sp = draft.pop("_current_sponsor", None)
    if sp:
        draft.setdefault("sponsors", []).append(sp)
    await state.update_data(draft=draft)
    await state.set_state(StepStates.op_add_sponsor)
    text = (
        f"✅ Спонсор добавлен.\n"
        f"Всего спонсоров: <b>{len(draft.get('sponsors', []))}</b>\n\n"
        f"Добавить ещё или закончить?"
    )
    msg = target.message if hasattr(target, "message") else target
    try:
        await msg.edit_text(text, reply_markup=add_sponsor_now_kb())
    except Exception:
        await msg.answer(text, reply_markup=add_sponsor_now_kb())


@router.callback_query(StepStates.op_sponsor_button_color, F.data.startswith("spclr:"))
async def cb_op_sp_color(cb: CallbackQuery, state: FSMContext) -> None:
    color = cb.data.split(":")[1]
    data = await state.get_data()
    draft = data["draft"]
    draft.setdefault("_current_sponsor", {})["button_color"] = color
    await state.update_data(draft=draft)
    await state.set_state(StepStates.op_sponsor_button_emoji)
    await cb.message.edit_text(_PREMIUM_PROMPT, reply_markup=_skip_emoji_kb("spemoji:skip"))
    await cb.answer()


@router.callback_query(StepStates.op_sponsor_button_emoji, F.data == "spemoji:skip")
async def cb_op_sp_emoji_skip(cb: CallbackQuery, state: FSMContext) -> None:
    await _finish_op_sponsor(cb, state)
    await cb.answer()


@router.message(StepStates.op_sponsor_button_emoji)
async def m_op_sp_emoji(message: Message, state: FSMContext) -> None:
    emoji_id = _extract_custom_emoji_id(message)
    if not emoji_id:
        await message.answer(
            "Не нашёл премиум-эмодзи. Пришли его или нажми «Пропустить».",
            reply_markup=_skip_emoji_kb("spemoji:skip"),
        )
        return
    data = await state.get_data()
    draft = data["draft"]
    draft.setdefault("_current_sponsor", {})["icon_custom_emoji_id"] = emoji_id
    await state.update_data(draft=draft)
    await _finish_op_sponsor(message, state)


@router.callback_query(StepStates.op_add_sponsor, F.data == "sp:done")
async def cb_op_sp_done(cb: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    draft = data["draft"]
    if not draft.get("sponsors"):
        await cb.answer("Добавь хотя бы одного спонсора!", show_alert=True)
        return
    await state.set_state(StepStates.op_check_btn_text)
    await cb.message.edit_text(
        "✅ Спонсоры готовы.\n\n"
        "Теперь пришли <b>текст кнопки «Проверить»</b>.\n"
        "Например: <code>✅ Проверить подписку</code>"
    )
    await cb.answer()


@router.message(StepStates.op_check_btn_text)
async def m_op_check_text(message: Message, state: FSMContext) -> None:
    txt = (message.text or "").strip()
    if not txt:
        await message.answer("Пришли текст.")
        return
    data = await state.get_data()
    draft = data["draft"]
    draft["check_button_text"] = txt
    await state.update_data(draft=draft)
    await state.set_state(StepStates.op_check_btn_color)
    await message.answer(
        "Выбери <b>цвет/префикс</b> кнопки проверки:",
        reply_markup=color_picker("opclr"),
    )


async def _after_check_btn(target, state: FSMContext) -> None:
    await state.set_state(StepStates.op_duplicate_after)
    text = (
        "⏱ <b>Время между дублями</b>: через сколько секунд писать "
        "повторно, если юзер не пройдёт ОП?\nПришли число."
    )
    msg = target.message if hasattr(target, "message") else target
    try:
        await msg.edit_text(text)
    except Exception:
        await msg.answer(text)


@router.callback_query(StepStates.op_check_btn_color, F.data.startswith("opclr:"))
async def cb_op_check_color(cb: CallbackQuery, state: FSMContext) -> None:
    color = cb.data.split(":")[1]
    data = await state.get_data()
    draft = data["draft"]
    draft["check_button_color"] = color
    await state.update_data(draft=draft)
    await state.set_state(StepStates.op_check_btn_emoji)
    await cb.message.edit_text(_PREMIUM_PROMPT, reply_markup=_skip_emoji_kb("opemoji:skip"))
    await cb.answer()


@router.callback_query(StepStates.op_check_btn_emoji, F.data == "opemoji:skip")
async def cb_op_check_emoji_skip(cb: CallbackQuery, state: FSMContext) -> None:
    await _after_check_btn(cb, state)
    await cb.answer()


@router.message(StepStates.op_check_btn_emoji)
async def m_op_check_emoji(message: Message, state: FSMContext) -> None:
    emoji_id = _extract_custom_emoji_id(message)
    if not emoji_id:
        await message.answer(
            "Не нашёл премиум-эмодзи. Пришли его или нажми «Пропустить».",
            reply_markup=_skip_emoji_kb("opemoji:skip"),
        )
        return
    data = await state.get_data()
    draft = data["draft"]
    draft["check_button_custom_emoji_id"] = emoji_id
    await state.update_data(draft=draft)
    await _after_check_btn(message, state)


@router.message(StepStates.op_duplicate_after)
async def m_op_dup_after(message: Message, state: FSMContext) -> None:
    try:
        v = int(message.text.strip())
        if v < 1:
            raise ValueError
    except (ValueError, AttributeError):
        await message.answer("Нужно положительное целое.")
        return
    data = await state.get_data()
    draft = data["draft"]
    draft["duplicate_after"] = v
    await state.update_data(draft=draft)
    await state.set_state(StepStates.op_duplicate_increment)
    await message.answer(
        "📈 <b>Прирост</b>: насколько увеличивать интервал с каждым дублем (0 — не увеличивать)?"
    )


@router.message(StepStates.op_duplicate_increment)
async def m_op_dup_inc(message: Message, state: FSMContext) -> None:
    try:
        v = int(message.text.strip())
        if v < 0:
            raise ValueError
    except (ValueError, AttributeError):
        await message.answer("Нужно неотрицательное целое.")
        return
    data = await state.get_data()
    draft = data["draft"]
    draft["duplicate_increment"] = v
    await state.update_data(draft=draft)
    await state.set_state(StepStates.op_duplicate_max)
    await message.answer("🔁 <b>Макс. число дублей</b>: пришли число.")


@router.message(StepStates.op_duplicate_max)
async def m_op_dup_max(message: Message, state: FSMContext) -> None:
    try:
        v = int(message.text.strip())
        if v < 0:
            raise ValueError
    except (ValueError, AttributeError):
        await message.answer("Нужно неотрицательное целое.")
        return
    data = await state.get_data()
    draft = data["draft"]
    draft["duplicate_max"] = v
    await state.update_data(draft=draft)
    await state.set_state(StepStates.op_skip_timer)
    await message.answer(
        "⏭ <b>Таймер пропуска ОП</b>: сколько секунд ждать после того, "
        "как дубли закончились, прежде чем пропустить ОП и пойти дальше?\n\n"
        "Пришли число (0 — переходить сразу)."
    )


@router.message(StepStates.op_skip_timer)
async def m_op_skip_timer(message: Message, state: FSMContext) -> None:
    try:
        v = int(message.text.strip())
        if v < 0:
            raise ValueError
    except (ValueError, AttributeError):
        await message.answer("Нужно неотрицательное целое (0 или больше).")
        return
    data = await state.get_data()
    draft = data["draft"]
    bot_id = int(data["bot_id"])
    draft["skip_timer"] = v

    cfg = {
        "text": draft.get("text") or "",
        "photo_file_id": draft.get("photo_file_id"),
        "sponsors": draft.get("sponsors", []),
        "check_button_text": draft.get("check_button_text") or "✅ Проверить",
        "check_button_color": draft.get("check_button_color") or "green",
        "check_button_custom_emoji_id": draft.get("check_button_custom_emoji_id"),
        "skip_timer": int(draft.get("skip_timer", 0) or 0),
    }
    await get_db().add_step(
        bot_id, "op", cfg,
        duplicate_after=draft.get("duplicate_after", 60),
        duplicate_increment=draft.get("duplicate_increment", 0),
        duplicate_max=v,
    )
    await state.clear()
    steps = await get_db().list_steps(bot_id)
    await message.answer(
        "✅ Шаг <b>ОП</b> добавлен!",
        reply_markup=scenario_menu(bot_id, steps),
    )


# ============================================================================
# СООБЩЕНИЕ
# ============================================================================

@router.message(StepStates.msg_content)
async def m_msg_content(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    draft = data.get("draft", {})
    extracted = _extract_content(message)
    if not any(extracted.values()):
        await message.answer("Не понял контент. Пришли текст, фото, гифку или перешли пост.")
        return
    draft.update(extracted)
    draft.setdefault("buttons", [])
    await state.update_data(draft=draft)
    await state.set_state(StepStates.msg_add_buttons)
    await message.answer(
        f"✅ Контент принят.\n\nКнопок: <b>{len(draft['buttons'])}</b>\n\n"
        f"Добавим кнопки (со ссылками)?",
        reply_markup=add_button_now_kb(),
    )


@router.callback_query(StepStates.msg_add_buttons, F.data == "btn:add")
async def cb_msg_btn_add(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(StepStates.msg_add_button_text)
    await cb.message.edit_text("Пришли <b>текст кнопки</b>.")
    await cb.answer()


@router.message(StepStates.msg_add_button_text)
async def m_msg_btn_text(message: Message, state: FSMContext) -> None:
    txt = (message.text or "").strip()
    if not txt:
        await message.answer("Пришли текст.")
        return
    data = await state.get_data()
    draft = data["draft"]
    draft.setdefault("_current_button", {})["text"] = txt
    await state.update_data(draft=draft)
    await state.set_state(StepStates.msg_add_button_url)
    await message.answer("Теперь <b>ссылку</b> для этой кнопки (URL).")


@router.message(StepStates.msg_add_button_url)
async def m_msg_btn_url(message: Message, state: FSMContext) -> None:
    url = (message.text or "").strip()
    if not (url.startswith("http://") or url.startswith("https://") or url.startswith("tg://")):
        await message.answer("Это не ссылка. Пришли URL.")
        return
    data = await state.get_data()
    draft = data["draft"]
    draft["_current_button"]["url"] = url
    await state.update_data(draft=draft)
    await state.set_state(StepStates.msg_add_button_color)
    await message.answer(
        "Выбери <b>цвет/префикс</b> кнопки:",
        reply_markup=color_picker("mbclr"),
    )


def _skip_emoji_kb(cb: str = "mbemoji:skip"):
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="⏭ Пропустить", callback_data=cb),
    ]])


def _extract_custom_emoji_id(message: Message):
    """custom_emoji_id первого премиум-эмодзи в сообщении, либо None."""
    for e in (message.entities or []):
        if getattr(e, "type", None) == "custom_emoji":
            return e.custom_emoji_id
    return None


_PREMIUM_PROMPT = (
    "💎 Хочешь <b>премиум-эмодзи на кнопку</b>?\n\n"
    "Пришли сообщение, где есть нужный премиум-эмодзи (одним эмодзи), "
    "или нажми «Пропустить»."
)


async def _finish_msg_button(target, state: FSMContext) -> None:
    """Финализирует текущую кнопку (target — Message или CallbackQuery)."""
    data = await state.get_data()
    draft = data["draft"]
    btn = draft.pop("_current_button", None)
    if btn:
        draft.setdefault("buttons", []).append(btn)
    await state.update_data(draft=draft)
    await state.set_state(StepStates.msg_add_buttons)
    text = (
        f"✅ Кнопка добавлена.\nВсего: <b>{len(draft.get('buttons', []))}</b>\n\n"
        f"Добавить ещё или закончить?"
    )
    msg = target.message if hasattr(target, "message") else target
    try:
        await msg.edit_text(text, reply_markup=add_button_now_kb())
    except Exception:
        await msg.answer(text, reply_markup=add_button_now_kb())


@router.callback_query(StepStates.msg_add_button_color, F.data.startswith("mbclr:"))
async def cb_msg_btn_color(cb: CallbackQuery, state: FSMContext) -> None:
    color = cb.data.split(":")[1]
    data = await state.get_data()
    draft = data["draft"]
    draft.setdefault("_current_button", {})["color"] = color
    await state.update_data(draft=draft)
    await state.set_state(StepStates.msg_add_button_emoji)
    await cb.message.edit_text(
        "💎 Хочешь <b>премиум-эмодзи на кнопку</b>?\n\n"
        "Пришли сообщение, где есть нужный премиум-эмодзи (одним эмодзи), "
        "или нажми «Пропустить».",
        reply_markup=_skip_emoji_kb(),
    )
    await cb.answer()


@router.callback_query(StepStates.msg_add_button_emoji, F.data == "mbemoji:skip")
async def cb_msg_btn_emoji_skip(cb: CallbackQuery, state: FSMContext) -> None:
    await _finish_msg_button(cb, state)
    await cb.answer()


@router.message(StepStates.msg_add_button_emoji)
async def m_msg_btn_emoji(message: Message, state: FSMContext) -> None:
    emoji_id = _extract_custom_emoji_id(message)
    if not emoji_id:
        await message.answer(
            "Не нашёл премиум-эмодзи в сообщении. Пришли сообщение, состоящее из "
            "премиум-эмодзи, или нажми «Пропустить».",
            reply_markup=_skip_emoji_kb(),
        )
        return
    data = await state.get_data()
    draft = data["draft"]
    draft.setdefault("_current_button", {})["icon_custom_emoji_id"] = emoji_id
    await state.update_data(draft=draft)
    await _finish_msg_button(message, state)


@router.callback_query(StepStates.msg_buttons_layout, F.data.startswith("blay:"))
async def cb_msg_buttons_layout(cb: CallbackQuery, state: FSMContext) -> None:
    layout = cb.data.split(":")[1]  # vertical | grid
    data = await state.get_data()
    draft = data["draft"]
    # layout = "1" | "2" | "3" — число кнопок в ряд
    try:
        draft["buttons_layout"] = max(1, min(3, int(layout)))
    except (ValueError, TypeError):
        draft["buttons_layout"] = 2
    await state.update_data(draft=draft)
    await state.set_state(StepStates.msg_wait_mode)
    await cb.message.edit_text(
        "Раскладка сохранена.\n\nТеперь выбери режим ожидания:",
        reply_markup=msg_wait_mode_kb(),
    )
    await cb.answer()


@router.callback_query(StepStates.msg_add_buttons, F.data == "btn:done")
async def cb_msg_btn_done(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(StepStates.msg_wait_mode)
    await cb.message.edit_text(
        "<b>⏳ Режим ожидания</b>\n\n"
        "Как переходить на следующий шаг?",
        reply_markup=msg_wait_mode_kb(),
    )
    await cb.answer()


@router.callback_query(StepStates.msg_wait_mode, F.data.startswith("wm:"))
async def cb_msg_wm(cb: CallbackQuery, state: FSMContext) -> None:
    mode = cb.data.split(":")[1]
    data = await state.get_data()
    draft = data["draft"]
    draft["wait_mode"] = mode
    await state.update_data(draft=draft)
    if mode == "timer":
        await state.set_state(StepStates.msg_wait_timer)
        await cb.message.edit_text(
            "⏱ Пришли <b>таймер</b> в секундах — через сколько перейти к следующему шагу."
        )
        await cb.answer()
        return
    elif mode == "user_message":
        await state.set_state(StepStates.msg_keyboard_choice)
        await cb.message.edit_text(
            "<b>⌨️ Кнопка-клавиатура</b>\n\n"
            "Хочешь добавить юзеру кнопку на нижней клавиатуре, при нажатии "
            "на которую сценарий продолжится? Это упростит переход (а не "
            "набирать сообщение вручную).",
            reply_markup=back_to_kb_choice(),
        )
    else:  # none — без ожидания, дубли не нужны, сохраняем сразу
        await _finalize_msg_step(cb.message, state)
        await cb.answer()
        return
    await cb.answer()


def back_to_kb_choice():
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Да, добавить", callback_data="kbc:1"),
        InlineKeyboardButton(text="🚫 Нет", callback_data="kbc:0"),
    ]])


@router.message(StepStates.msg_wait_timer)
async def m_msg_wait_timer(message: Message, state: FSMContext) -> None:
    try:
        v = int(message.text.strip())
        if v < 1:
            raise ValueError
    except (ValueError, AttributeError):
        await message.answer("Нужно положительное целое.")
        return
    data = await state.get_data()
    draft = data["draft"]
    draft["wait_timer"] = v
    await state.update_data(draft=draft)
    # Таймер сам продвинет сценарий — дубли не нужны, сохраняем шаг сразу.
    await _finalize_msg_step(message, state)


@router.callback_query(StepStates.msg_keyboard_choice, F.data.startswith("kbc:"))
async def cb_msg_kb_choice(cb: CallbackQuery, state: FSMContext) -> None:
    yes = cb.data.split(":")[1] == "1"
    if not yes:
        await state.set_state(StepStates.msg_duplicate_after)
        await cb.message.edit_text("⏱ <b>Время между дублями</b>: пришли число секунд.")
        await cb.answer()
        return
    await state.set_state(StepStates.msg_keyboard_text)
    await cb.message.edit_text(
        "Пришли <b>текст кнопки</b>, которая появится у юзера на клавиатуре."
    )
    await cb.answer()


@router.message(StepStates.msg_keyboard_text)
async def m_msg_kb_text(message: Message, state: FSMContext) -> None:
    txt = (message.text or "").strip()
    if not txt:
        await message.answer("Пришли текст.")
        return
    data = await state.get_data()
    draft = data["draft"]
    draft["keyboard_text"] = txt
    await state.update_data(draft=draft)
    await state.set_state(StepStates.msg_duplicate_after)
    await message.answer("⏱ <b>Время между дублями</b>: пришли число секунд.")


@router.message(StepStates.msg_duplicate_after)
async def m_msg_dup_after(message: Message, state: FSMContext) -> None:
    try:
        v = int(message.text.strip())
        if v < 1:
            raise ValueError
    except (ValueError, AttributeError):
        await message.answer("Нужно положительное целое.")
        return
    data = await state.get_data()
    draft = data["draft"]
    draft["duplicate_after"] = v
    await state.update_data(draft=draft)
    await state.set_state(StepStates.msg_duplicate_increment)
    await message.answer("📈 <b>Прирост</b> между дублями: пришли число (0 — не увеличивать).")


@router.message(StepStates.msg_duplicate_increment)
async def m_msg_dup_inc(message: Message, state: FSMContext) -> None:
    try:
        v = int(message.text.strip())
        if v < 0:
            raise ValueError
    except (ValueError, AttributeError):
        await message.answer("Нужно неотрицательное целое.")
        return
    data = await state.get_data()
    draft = data["draft"]
    draft["duplicate_increment"] = v
    await state.update_data(draft=draft)
    await state.set_state(StepStates.msg_duplicate_max)
    await message.answer("🔁 <b>Макс. число дублей</b>: пришли число.")


async def _finalize_msg_step(target, state: FSMContext) -> None:
    """Сохраняет шаг «Сообщение». target — Message или CallbackQuery.message."""
    data = await state.get_data()
    draft = data["draft"]
    bot_id = int(data["bot_id"])
    cfg = {
        "text": draft.get("text") or "",
        "photo_file_id": draft.get("photo_file_id"),
        "sticker_file_id": draft.get("sticker_file_id"),
        "animation_file_id": draft.get("animation_file_id"),
        "video_file_id": draft.get("video_file_id"),
        "document_file_id": draft.get("document_file_id"),
        "copy_from": draft.get("copy_from"),
        "buttons": draft.get("buttons", []),
        "buttons_layout": draft.get("buttons_layout") or 2,
        "wait_mode": draft.get("wait_mode") or "none",
        "wait_timer": draft.get("wait_timer", 0),
        "keyboard_text": draft.get("keyboard_text"),
    }
    await get_db().add_step(
        bot_id, "message", cfg,
        duplicate_after=draft.get("duplicate_after", 60),
        duplicate_increment=draft.get("duplicate_increment", 0),
        duplicate_max=draft.get("duplicate_max", 0),
    )
    await state.clear()
    steps = await get_db().list_steps(bot_id)
    await target.answer(
        "✅ Шаг <b>Сообщение</b> добавлен!",
        reply_markup=scenario_menu(bot_id, steps),
    )


@router.message(StepStates.msg_duplicate_max)
async def m_msg_dup_max(message: Message, state: FSMContext) -> None:
    try:
        v = int(message.text.strip())
        if v < 0:
            raise ValueError
    except (ValueError, AttributeError):
        await message.answer("Нужно неотрицательное целое.")
        return
    data = await state.get_data()
    draft = data["draft"]
    bot_id = int(data["bot_id"])

    cfg: dict[str, Any] = {
        "text": draft.get("text") or "",
        "photo_file_id": draft.get("photo_file_id"),
        "sticker_file_id": draft.get("sticker_file_id"),
        "animation_file_id": draft.get("animation_file_id"),
        "video_file_id": draft.get("video_file_id"),
        "document_file_id": draft.get("document_file_id"),
        "copy_from": draft.get("copy_from"),
        "buttons": draft.get("buttons", []),
        "wait_mode": draft.get("wait_mode") or "none",
        "wait_timer": draft.get("wait_timer", 0),
        "keyboard_text": draft.get("keyboard_text"),
    }
    await get_db().add_step(
        bot_id, "message", cfg,
        duplicate_after=draft.get("duplicate_after", 60),
        duplicate_increment=draft.get("duplicate_increment", 0),
        duplicate_max=v,
    )
    await state.clear()
    steps = await get_db().list_steps(bot_id)
    await message.answer(
        "✅ Шаг <b>Сообщение</b> добавлен!",
        reply_markup=scenario_menu(bot_id, steps),
    )
