#!/usr/bin/env python3
"""
Патч 10: фикс формата кнопок.

Старый код scenario.py ожидает buttons ПЛОСКИМ списком [{text,url}, ...]
и сам группирует по 2 в ряд. Патчи 7/9 сохраняли список рядов [[...]] —
из-за этого advance падал с AttributeError: 'list' object has no attribute 'get',
и сценарий не переходил к следующему шагу.

Фикс: cb_copy_buttons_choice сохраняет кнопки плоским списком.
"""
from pathlib import Path

ROOT = Path("/opt/bot")
SC = ROOT / "handlers/step_create.py"

src = SC.read_text(encoding="utf-8")

# Старый (битый) вариант из патча 7
old = '''    if choice == "keep" and orig:
        # Конвертируем формат _orig_buttons -> buttons (text/url)
        draft["buttons"] = [
            [{"text": b["text"], "url": b.get("url", "")} for b in row if b.get("url")]
            for row in orig
        ]
        draft["buttons"] = [r for r in draft["buttons"] if r]'''

new = '''    if choice == "keep" and orig:
        # Конвертируем _orig_buttons (список рядов) -> ПЛОСКИЙ список,
        # потому что scenario.py сам группирует кнопки по 2 в ряд.
        flat = []
        for row in orig:
            for b in row:
                if b.get("url"):
                    flat.append({"text": b["text"], "url": b["url"]})
        draft["buttons"] = flat'''

if old not in src:
    # Возможно патч 7 вставлял слегка иначе — пробуем найти по сигнатуре
    raise SystemExit(
        "Не нашёл блок keep-кнопок. Покажи `grep -n 'choice == \"keep\"' "
        "/opt/bot/handlers/step_create.py` и пришли — подгоню патч."
    )

src = src.replace(old, new, 1)
SC.write_text(src, encoding="utf-8")
print("  ✓ handlers/step_create.py — кнопки теперь плоским списком")

# На случай, если в БД уже сохранён битый шаг — чиним существующие шаги
import sqlite3, json, glob

db_paths = ["/opt/bot/data.db"]
for dbp in db_paths:
    if not Path(dbp).exists():
        continue
    conn = sqlite3.connect(dbp)
    cur = conn.execute("SELECT id, config FROM steps WHERE step_type='message'")
    fixed = 0
    for sid, cfg_raw in cur.fetchall():
        try:
            cfg = json.loads(cfg_raw)
        except Exception:
            continue
        btns = cfg.get("buttons")
        # Если buttons это список списков — расплющиваем
        if isinstance(btns, list) and btns and isinstance(btns[0], list):
            flat = []
            for row in btns:
                if isinstance(row, list):
                    for b in row:
                        if isinstance(b, dict) and b.get("url"):
                            flat.append({"text": b.get("text", ""), "url": b["url"]})
                elif isinstance(row, dict):
                    flat.append(row)
            cfg["buttons"] = flat
            conn.execute("UPDATE steps SET config=? WHERE id=?",
                         (json.dumps(cfg, ensure_ascii=False), sid))
            fixed += 1
    conn.commit()
    conn.close()
    if fixed:
        print(f"  ✓ Починено битых шагов в БД: {fixed}")
    else:
        print("  ✓ Битых шагов в БД не найдено")

print("\n✅ Патч 10 применён. Перезапусти: systemctl restart bot")
