#!/usr/bin/env python3
"""
Патч 14:
1. БАГ ТАЙМЕРА: _timer_advance клался в _dup_tasks и сам звал advance,
   а advance отменяет этот слот → задача убивала себя CancelledError'ом.
   Фикс: advance запускается отдельной задачей (как уже сделано для дублей).
2. БАГ «БЕЗ ОЖИДАНИЯ»: для wait_mode=='none' не было вызова advance —
   сценарий замирал. Фикс: добавлен advance отдельной задачей.
3. Вертикальная раскладка кнопок message-шага: при создании шага
   спрашивается «вертикально / по 2 в ряд», раскладка хранится в cfg.
"""
import json
import re
import sqlite3
from pathlib import Path

ROOT = Path("/opt/bot")


def patch(path: Path, old: str, new: str, label: str):
    src = path.read_text(encoding="utf-8")
    if old not in src:
        raise SystemExit(f"NOT FOUND ({label}) in {path.name}:\n---\n{old[:300]}\n---")
    src = src.replace(old, new, 1)
    path.write_text(src, encoding="utf-8")
    print(f"  ✓ {path.relative_to(ROOT)} — {label}")


SN = ROOT / "bots/scenario.py"

# === 1. ФИКС ТАЙМЕРА ===
patch(
    SN,
    '''        if step_type == "message" and cfg.get("wait_mode") == "timer":
            timer = int(cfg.get("wait_timer", 0))
            if timer > 0:
                async def _timer_advance() -> None:
                    try:
                        await asyncio.sleep(timer)
                        # Записываем прохождение
                        await get_db().record_step_completion(user_id, step["id"])
                        await self.advance(bot, bot_record, user_id)
                    except asyncio.CancelledError:
                        pass
                # Используем dup_tasks слот для этой задачи (она тоже будет отменена при advance)
                key = (bot_record["id"], user_id)
                old = self._dup_tasks.pop(key, None)
                if old:
                    old.cancel()
                self._dup_tasks[key] = asyncio.create_task(_timer_advance())
                return''',
    '''        if step_type == "message" and cfg.get("wait_mode") == "timer":
            timer = int(cfg.get("wait_timer", 0))
            if timer > 0:
                async def _timer_advance() -> None:
                    try:
                        await asyncio.sleep(timer)
                        await get_db().record_step_completion(user_id, step["id"])
                    except asyncio.CancelledError:
                        return
                    # advance запускаем ОТДЕЛЬНОЙ задачей: advance вызовет
                    # _cancel_dup, который отменит наш же слот в _dup_tasks.
                    # Если звать advance напрямую — задача убьёт сама себя
                    # CancelledError'ом раньше, чем отправит следующий шаг.
                    asyncio.create_task(self.advance(bot, bot_record, user_id))
                key = (bot_record["id"], user_id)
                old = self._dup_tasks.pop(key, None)
                if old:
                    old.cancel()
                self._dup_tasks[key] = asyncio.create_task(_timer_advance())
                return''',
    "фикс таймера (advance в отдельной задаче)",
)

# === 2. ФИКС «БЕЗ ОЖИДАНИЯ» ===
# После блоков timer и user_message, если wait_mode == 'none' — нужно advance.
# Вставляем сразу после блока user_message.
patch(
    SN,
    '''        # Если ждём сообщение от юзера — устанавливаем флаг
        if step_type == "message" and cfg.get("wait_mode") == "user_message":
            kb_text = cfg.get("keyboard_text") or None
            await db.update_user(user_id, awaiting_user_msg=1, awaiting_kb_text=kb_text)''',
    '''        # Если ждём сообщение от юзера — устанавливаем флаг
        if step_type == "message" and cfg.get("wait_mode") == "user_message":
            kb_text = cfg.get("keyboard_text") or None
            await db.update_user(user_id, awaiting_user_msg=1, awaiting_kb_text=kb_text)

        # Режим «без ожидания»: сообщение показано — сразу идём дальше.
        # advance отдельной задачей, чтобы не конфликтовать с _cancel_dup.
        if step_type == "message" and cfg.get("wait_mode") in (None, "", "none"):
            await get_db().record_step_completion(user_id, step["id"])
            asyncio.create_task(self.advance(bot, bot_record, user_id))''',
    "фикс «без ожидания» (добавлен advance)",
)

# === 3. ВЕРТИКАЛЬНАЯ РАСКЛАДКА КНОПОК ===
# 3a. build_inline_keyboard учитывает layout. Меняем _send_message_step:
# rows строятся по cfg["buttons_layout"] ('vertical' = по 1, иначе по 2).
src = SN.read_text(encoding="utf-8")
m = re.search(
    r'(\n        rows: list\[list\[dict\]\] = \[\]\n'
    r'        for i in range\(0, len\(_flat\), 2\):\n'
    r'            rows\.append\(_flat\[i : i \+ 2\]\)\n)',
    src,
)
if m:
    old_rows = m.group(1)
    new_rows = '''
        # Раскладка: 'vertical' — каждая кнопка в своём ряду, иначе по 2.
        _per_row = 1 if cfg.get("buttons_layout") == "vertical" else 2
        rows: list[list[dict]] = []
        for i in range(0, len(_flat), _per_row):
            rows.append(_flat[i : i + _per_row])
'''
    src = src.replace(old_rows, new_rows, 1)
    SN.write_text(src, encoding="utf-8")
    print("  ✓ bots/scenario.py — раскладка кнопок (vertical/2-в-ряд)")
else:
    print("  ⚠ блок rows не найден в _send_message_step — проверь патч 12")

# 3b. step_create.py — спросить раскладку при создании шага.
SC = ROOT / "handlers/step_create.py"
# Новый стейт
FSM = ROOT / "states/fsm.py"
fsm_src = FSM.read_text(encoding="utf-8")
if "msg_buttons_layout" not in fsm_src:
    fsm_src = fsm_src.replace(
        "    msg_copy_buttons_choice = State()",
        "    msg_copy_buttons_choice = State()\n    msg_buttons_layout = State()",
    )
    FSM.write_text(fsm_src, encoding="utf-8")
    print("  ✓ states/fsm.py — стейт msg_buttons_layout")

# В cb_msg_btn_done (btn:done) — если кнопки есть, спросить раскладку.
sc_src = SC.read_text(encoding="utf-8")
old_done = '''@router.callback_query(StepStates.msg_add_buttons, F.data == "btn:done")'''
new_done = '''@router.callback_query(StepStates.msg_buttons_layout, F.data.startswith("blay:"))
async def cb_msg_buttons_layout(cb: CallbackQuery, state: FSMContext) -> None:
    layout = cb.data.split(":")[1]  # vertical | grid
    data = await state.get_data()
    draft = data["draft"]
    draft["buttons_layout"] = "vertical" if layout == "vertical" else "grid"
    await state.update_data(draft=draft)
    await state.set_state(StepStates.msg_wait_mode)
    await cb.message.edit_text(
        "Раскладка сохранена.\\n\\nТеперь выбери режим ожидания:",
        reply_markup=msg_wait_mode_kb(),
    )
    await cb.answer()


@router.callback_query(StepStates.msg_add_buttons, F.data == "btn:done")'''
sc_src = sc_src.replace(old_done, new_done, 1)

# Тело cb_msg_btn_done: вместо перехода к wait_mode — спросить раскладку,
# но только если кнопок >= 2 (для 0-1 кнопок раскладка не нужна).
old_body = '''    await state.set_state(StepStates.msg_wait_mode)
    await cb.message.edit_text(
        "Выбери, что делать после показа сообщения:",
        reply_markup=msg_wait_mode_kb(),
    )
    await cb.answer()'''
new_body = '''    data = await state.get_data()
    draft = data.get("draft", {})
    btns = draft.get("buttons", [])
    if len(btns) >= 2:
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
        await state.set_state(StepStates.msg_buttons_layout)
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="↕️ Вертикально (по 1 в ряд)", callback_data="blay:vertical")],
            [InlineKeyboardButton(text="↔️ По 2 в ряд", callback_data="blay:grid")],
        ])
        await cb.message.edit_text("Как расположить кнопки?", reply_markup=kb)
        await cb.answer()
        return
    await state.set_state(StepStates.msg_wait_mode)
    await cb.message.edit_text(
        "Выбери, что делать после показа сообщения:",
        reply_markup=msg_wait_mode_kb(),
    )
    await cb.answer()'''
if old_body in sc_src:
    sc_src = sc_src.replace(old_body, new_body, 1)
    SC.write_text(sc_src, encoding="utf-8")
    print("  ✓ handlers/step_create.py — выбор раскладки кнопок")
else:
    SC.write_text(sc_src, encoding="utf-8")
    print("  ⚠ тело cb_msg_btn_done иное — добавлен только обработчик blay,")
    print("    раскладку нужно подключить вручную (покажи cb_msg_btn_done)")

print("\n✅ Патч 14 применён. Перезапусти: systemctl restart bot")
