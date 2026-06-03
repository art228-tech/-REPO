#!/usr/bin/env python3
"""
Патч 12: железобетонный фикс кнопок.

_send_message_step теперь сам нормализует buttons независимо от того,
в каком формате они лежат в БД (плоский список или список рядов).
Плюс — дочищает БД от битых шагов (на случай если патч 10 не доработал).
"""
import json
import sqlite3
from pathlib import Path

ROOT = Path("/opt/bot")
SN = ROOT / "bots/scenario.py"

src = SN.read_text(encoding="utf-8")

old = '''        buttons = cfg.get("buttons", [])
        rows: list[list[dict]] = []
        for i in range(0, len(buttons), 2):
            rows.append(buttons[i : i + 2])
        markup = build_inline_keyboard(rows)'''

new = '''        # Нормализуем buttons: в БД может лежать и плоский список [{..}],
        # и список рядов [[{..}]]. Приводим к плоскому списку словарей.
        _raw = cfg.get("buttons", []) or []
        _flat: list[dict] = []
        for _item in _raw:
            if isinstance(_item, dict):
                _flat.append(_item)
            elif isinstance(_item, list):
                for _b in _item:
                    if isinstance(_b, dict):
                        _flat.append(_b)
        rows: list[list[dict]] = []
        for i in range(0, len(_flat), 2):
            rows.append(_flat[i : i + 2])
        markup = build_inline_keyboard(rows)'''

if old not in src:
    raise SystemExit("Блок buttons в _send_message_step не найден — "
                     "покажи `sed -n '320,330p' /opt/bot/bots/scenario.py`")

src = src.replace(old, new, 1)
SN.write_text(src, encoding="utf-8")
print("  ✓ bots/scenario.py — buttons нормализуются в рантайме")

# Дочистка БД — расплющиваем все битые buttons во всех шагах
dbp = "/opt/bot/data.db"
if Path(dbp).exists():
    conn = sqlite3.connect(dbp)
    cur = conn.execute("SELECT id, config FROM steps")
    fixed = 0
    for sid, cfg_raw in cur.fetchall():
        try:
            cfg = json.loads(cfg_raw)
        except Exception:
            continue
        btns = cfg.get("buttons")
        if not isinstance(btns, list) or not btns:
            continue
        # Если есть хоть один вложенный список — расплющиваем
        if any(isinstance(x, list) for x in btns):
            flat = []
            for x in btns:
                if isinstance(x, dict):
                    flat.append(x)
                elif isinstance(x, list):
                    for b in x:
                        if isinstance(b, dict):
                            flat.append(b)
            cfg["buttons"] = flat
            conn.execute("UPDATE steps SET config=? WHERE id=?",
                         (json.dumps(cfg, ensure_ascii=False), sid))
            fixed += 1
    conn.commit()
    conn.close()
    print(f"  ✓ Дочищено битых шагов в БД: {fixed}")

print("\n✅ Патч 12 применён. Перезапусти: systemctl restart bot")
