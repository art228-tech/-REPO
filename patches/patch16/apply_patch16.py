#!/usr/bin/env python3
"""
Патч 16: раскладка кнопок message-шага — выбор 1 / 2 / 3 в ряд.
buttons_layout теперь хранит число (1, 2 или 3) вместо vertical/grid.
Старые значения vertical/grid тоже понимаются (обратная совместимость).
"""
import json
import sqlite3
from pathlib import Path

ROOT = Path("/opt/friend_bot")  # для друга; для основного — заменить на /opt/bot


def patch(path: Path, old: str, new: str, label: str):
    src = path.read_text(encoding="utf-8")
    if old not in src:
        raise SystemExit(f"NOT FOUND ({label}) in {path.name}:\n---\n{old[:300]}\n---")
    src = src.replace(old, new, 1)
    path.write_text(src, encoding="utf-8")
    print(f"  ✓ {path.relative_to(ROOT)} — {label}")


SC = ROOT / "handlers/step_create.py"
SN = ROOT / "bots/scenario.py"

# === 1. Клавиатура выбора: 1 / 2 / 3 в ряд ===
patch(
    SC,
    '''        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="↕️ Вертикально (по 1 в ряд)", callback_data="blay:vertical")],
            [InlineKeyboardButton(text="↔️ По 2 в ряд", callback_data="blay:grid")],
        ])''',
    '''        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="1️⃣ По 1 в ряд (столбиком)", callback_data="blay:1")],
            [InlineKeyboardButton(text="2️⃣ По 2 в ряд", callback_data="blay:2")],
            [InlineKeyboardButton(text="3️⃣ По 3 в ряд", callback_data="blay:3")],
        ])''',
    "клавиатура 1/2/3 в ряд",
)

# === 2. Обработчик: сохраняем число ===
patch(
    SC,
    '''    draft["buttons_layout"] = "vertical" if layout == "vertical" else "grid"''',
    '''    # layout = "1" | "2" | "3" — число кнопок в ряд
    try:
        draft["buttons_layout"] = max(1, min(3, int(layout)))
    except (ValueError, TypeError):
        draft["buttons_layout"] = 2''',
    "обработчик сохраняет число",
)

# === 3. _finalize_msg_step: дефолт 2 (число, не "grid") ===
patch(
    SC,
    '''        "buttons_layout": draft.get("buttons_layout") or "grid",''',
    '''        "buttons_layout": draft.get("buttons_layout") or 2,''',
    "дефолт раскладки = 2",
)

# === 4. scenario.py: _per_row из числа (со старой совместимостью) ===
patch(
    SN,
    '''        _per_row = 1 if cfg.get("buttons_layout") == "vertical" else 2''',
    '''        # buttons_layout: число 1..3. Старые значения vertical/grid тоже ок.
        _bl = cfg.get("buttons_layout")
        if _bl == "vertical":
            _per_row = 1
        elif _bl == "grid":
            _per_row = 2
        else:
            try:
                _per_row = max(1, min(3, int(_bl)))
            except (ValueError, TypeError):
                _per_row = 2''',
    "_per_row из числа 1..3",
)

print("\n✅ Патч 16 применён. Перезапусти бот.")
