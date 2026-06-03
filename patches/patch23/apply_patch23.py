#!/usr/bin/env python3
"""
Патч 23: таймер пропуска ОП.
При создании ОП-шага после настройки дублей задаётся «таймер пропуска» —
сколько секунд ждать после того, как дубли кончились, прежде чем
пропустить ОП и пойти дальше по сценарию.

cfg["skip_timer"] — это число секунд (0 = сразу).
"""
from pathlib import Path

ROOT = Path("/opt/bot")  # для друга — /opt/friend_bot


def patch(path: Path, old: str, new: str, label: str):
    src = path.read_text(encoding="utf-8")
    if old not in src:
        raise SystemExit(f"NOT FOUND ({label}) in {path.name}:\n---\n{old[:300]}\n---")
    src = src.replace(old, new, 1)
    path.write_text(src, encoding="utf-8")
    print(f"  ✓ {path.relative_to(ROOT)} — {label}")


SC = ROOT / "handlers/step_create.py"
FSM = ROOT / "states/fsm.py"
SN = ROOT / "bots/scenario.py"

# === 1. Новый стейт op_skip_timer ===
fsm_src = FSM.read_text(encoding="utf-8")
if "op_skip_timer" not in fsm_src:
    fsm_src = fsm_src.replace(
        "    op_duplicate_max = State()",
        "    op_duplicate_max = State()\n    op_skip_timer = State()",
        1,
    )
    FSM.write_text(fsm_src, encoding="utf-8")
    print("  ✓ states/fsm.py — стейт op_skip_timer")

# === 2. step_create: после duplicate_max спрашиваем skip_timer ===
sc_src = SC.read_text(encoding="utf-8")

# 2a. m_op_dup_max больше не финализирует — ведёт на вопрос о таймере.
patch(
    SC,
    '''@router.message(StepStates.op_duplicate_max)
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
    bot_id = int(data["bot_id"])''',
    '''@router.message(StepStates.op_duplicate_max)
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
        "как дубли закончились, прежде чем пропустить ОП и пойти дальше?\\n\\n"
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
    draft["skip_timer"] = v''',
    "вопрос про skip_timer после дублей",
)

# 2b. в cfg ОП-шага добавляем skip_timer
patch(
    SC,
    '''    cfg = {
        "text": draft.get("text") or "",
        "photo_file_id": draft.get("photo_file_id"),
        "sponsors": draft.get("sponsors", []),
        "check_button_text": draft.get("check_button_text") or "✅ Проверить",
        "check_button_color": draft.get("check_button_color") or "green",
    }''',
    '''    cfg = {
        "text": draft.get("text") or "",
        "photo_file_id": draft.get("photo_file_id"),
        "sponsors": draft.get("sponsors", []),
        "check_button_text": draft.get("check_button_text") or "✅ Проверить",
        "check_button_color": draft.get("check_button_color") or "green",
        "skip_timer": int(draft.get("skip_timer", 0) or 0),
    }''',
    "skip_timer в cfg ОП-шага",
)

# === 3. scenario.py: после дублей ОП ждать skip_timer перед advance ===
# Блок «Лимит дублей достигнут» (после патча 22) — добавляем паузу для ОП.
patch(
    SN,
    '''                # Лимит дублей достигнут.
                user = await db.get_user(user_id)
                if not user or user["current_step_order"] != step["step_order"]:
                    return''',
    '''                # Лимит дублей достигнут.
                user = await db.get_user(user_id)
                if not user or user["current_step_order"] != step["step_order"]:
                    return
                # Для ОП-шага — ждём «таймер пропуска» перед переходом дальше.
                if step["step_type"] == "op":
                    try:
                        _cfg = json.loads(step["config"])
                        _skip = int(_cfg.get("skip_timer", 0) or 0)
                    except Exception:
                        _skip = 0
                    if _skip > 0:
                        await asyncio.sleep(_skip)
                        # перепроверяем, что юзер всё ещё на этом шаге
                        user = await db.get_user(user_id)
                        if not user or user["current_step_order"] != step["step_order"]:
                            return''',
    "пауза skip_timer для ОП перед переходом",
)

print("\\n✅ Патч 23 применён. Перезапусти: systemctl restart bot")
