#!/usr/bin/env python3
"""Патч 6: управление спонсорами (CRUD, перенос, тест)."""
import shutil
from pathlib import Path

ROOT = Path("/opt/bot")
HERE = Path(__file__).resolve().parent

# 1. Копируем sponsor_edit.py
src = HERE / "sponsor_edit.py"
dst = ROOT / "handlers/sponsor_edit.py"
shutil.copy(src, dst)
print(f"  ✓ {dst.relative_to(ROOT)}")

# 2. Регистрируем роутер в handlers/__init__.py
init = ROOT / "handlers/__init__.py"
s = init.read_text(encoding="utf-8")
if "sponsor_edit" not in s:
    s = s.replace(
        "from . import start, add_bot, bot_menu, scenario_edit, step_create, stats, broadcast, refs",
        "from . import start, add_bot, bot_menu, scenario_edit, step_create, stats, broadcast, refs, sponsor_edit",
    )
    s = s.replace(
        "    dp.include_router(refs.router)",
        "    dp.include_router(refs.router)\n    dp.include_router(sponsor_edit.router)",
    )
    init.write_text(s, encoding="utf-8")
print(f"  ✓ handlers/__init__.py")

# 3. В step_view добавляем кнопку «👥 Спонсоры» для шагов op
kbf = ROOT / "keyboards/constructor_kb.py"
ks = kbf.read_text(encoding="utf-8")
old = '''def step_view(step_id: int, bot_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⬆️ Вверх", callback_data=f"step_up:{step_id}"),
            InlineKeyboardButton(text="⬇️ Вниз", callback_data=f"step_dn:{step_id}"),
        ],
        [InlineKeyboardButton(text="🗑 Удалить шаг", callback_data=f"step_del:{step_id}")],
        [InlineKeyboardButton(text="« К сценарию", callback_data=f"scn:{bot_id}")],
    ])'''
new = '''def step_view(step_id: int, bot_id: int, step_type: str = "") -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text="⬆️ Вверх", callback_data=f"step_up:{step_id}"),
            InlineKeyboardButton(text="⬇️ Вниз", callback_data=f"step_dn:{step_id}"),
        ],
    ]
    if step_type == "op":
        rows.append([InlineKeyboardButton(text="👥 Спонсоры", callback_data=f"spons:{step_id}")])
    rows.append([InlineKeyboardButton(text="🗑 Удалить шаг", callback_data=f"step_del:{step_id}")])
    rows.append([InlineKeyboardButton(text="« К сценарию", callback_data=f"scn:{bot_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)'''
if old in ks:
    ks = ks.replace(old, new)
    kbf.write_text(ks, encoding="utf-8")
    print(f"  ✓ keyboards/constructor_kb.py")
else:
    print(f"  ⚠ step_view уже обновлён или паттерн отличается")

# 4. Передаём step_type в step_view() из scenario_edit
sef = ROOT / "handlers/scenario_edit.py"
ses = sef.read_text(encoding="utf-8")
for old, new in [
    ('reply_markup=step_view(step_id, step["bot_id"]))',
     'reply_markup=step_view(step_id, step["bot_id"], step["step_type"]))'),
]:
    ses = ses.replace(old, new)
sef.write_text(ses, encoding="utf-8")
print(f"  ✓ handlers/scenario_edit.py")

print("\n✅ Патч применён. Перезапусти: systemctl restart bot")
