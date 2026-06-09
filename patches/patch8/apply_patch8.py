#!/usr/bin/env python3
"""
Патч 8:
1. _extract_content читает forward_origin (новый Bot API) — пересланные
   посты снова дают copy_from и кнопки.
2. В мастере шага «Сообщение» вопросы про дубли (время/прирост/макс)
   задаются ТОЛЬКО при режиме «ждать сообщение». При таймере и
   «без ожидания» шаг сохраняется сразу.
"""
from pathlib import Path

ROOT = Path("/opt/bot")
SC = ROOT / "handlers/step_create.py"


def patch(path: Path, edits):
    src = path.read_text(encoding="utf-8")
    for old, new in edits:
        if old not in src:
            raise SystemExit(f"NOT FOUND in {path.name}:\n---\n{old[:250]}\n---")
        src = src.replace(old, new, 1)
    path.write_text(src, encoding="utf-8")
    print(f"  ✓ {path.relative_to(ROOT)}")


print("[1/2] forward_origin в _extract_content")
patch(SC, [
    ('''    if message.forward_from_chat and message.forward_from_message_id:
        cfg["copy_from"] = {
            "chat_id": message.forward_from_chat.id,
            "message_id": message.forward_from_message_id,
        }''',
     '''    # Telegram отдаёт данные о пересылке либо в старом forward_from_chat,
    # либо (в новых клиентах) в forward_origin. Берём оба варианта.
    _fwd_chat_id = None
    _fwd_msg_id = None
    if message.forward_from_chat and message.forward_from_message_id:
        _fwd_chat_id = message.forward_from_chat.id
        _fwd_msg_id = message.forward_from_message_id
    else:
        _origin = getattr(message, "forward_origin", None)
        if _origin is not None:
            _och = getattr(_origin, "chat", None)
            _omid = getattr(_origin, "message_id", None)
            if _och is not None and _omid is not None:
                _fwd_chat_id = _och.id
                _fwd_msg_id = _omid
    if _fwd_chat_id is not None and _fwd_msg_id is not None:
        cfg["copy_from"] = {
            "chat_id": _fwd_chat_id,
            "message_id": _fwd_msg_id,
        }'''),
])


print("[2/2] пропуск вопросов про дубли при таймере / без ожидания")

# 2a. Хелпер-финализатор. Вставляем перед m_msg_dup_max.
finalizer = '''async def _finalize_msg_step(target, state: FSMContext) -> None:
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
'''

patch(SC, [
    ("@router.message(StepStates.msg_duplicate_max)\n", finalizer),
])

# 2b. cb_msg_wm: при timer и none — НЕ идём в дубли, сразу финал
patch(SC, [
    ('''    if mode == "timer":
        await state.set_state(StepStates.msg_wait_timer)
        await cb.message.edit_text(
            "⏱ Пришли <b>таймер</b> в секундах — через сколько перейти к следующему шагу."
        )''',
     '''    if mode == "timer":
        await state.set_state(StepStates.msg_wait_timer)
        await cb.message.edit_text(
            "⏱ Пришли <b>таймер</b> в секундах — через сколько перейти к следующему шагу."
        )
        await cb.answer()
        return'''),
    # ветка none — сразу сохранить шаг
    ('''    else:  # none
        # сразу переходим к настройкам дублирования
        await state.set_state(StepStates.msg_duplicate_after)
        await cb.message.edit_text(
            "⏱ <b>Время между дублями</b>: пришли число секунд."
        )
    await cb.answer()''',
     '''    else:  # none — без ожидания, дубли не нужны, сохраняем сразу
        await _finalize_msg_step(cb.message, state)
        await cb.answer()
        return
    await cb.answer()'''),
])

# 2c. m_msg_wait_timer: после ввода таймера — сразу сохранить шаг (без дублей)
patch(SC, [
    ('''    draft["wait_timer"] = v
    await state.update_data(draft=draft)
    await state.set_state(StepStates.msg_duplicate_after)
    await message.answer(
        "⏱ <b>Время между дублями</b>: через сколько секунд писать повторно, "
        "если юзер не получил это сообщение или не нажал кнопку? Пришли число."
    )''',
     '''    draft["wait_timer"] = v
    await state.update_data(draft=draft)
    # Таймер сам продвинет сценарий — дубли не нужны, сохраняем шаг сразу.
    await _finalize_msg_step(message, state)'''),
])

print("\n✅ Патч 8 применён. Перезапусти: systemctl restart bot")
