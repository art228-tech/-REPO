#!/usr/bin/env python3
"""
Патч 15:
1. buttons_layout сохраняется в шаг (раньше терялся в _finalize_msg_step)
   — теперь вертикальная раскладка реально работает.
2. Авто-пропуск ОП (когда показывать нечего) больше НЕ пишет
   step_completions для ОП-шага → не завышает % прохождения ОП.
   При этом advance к следующему шагу остаётся — последующие
   сообщения не теряются.
3. Чистка таблицы pending_join_requests от записей старше 30 дней
   (она пухнет — у тебя уже 63k записей).
"""
import json
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


# === 1. buttons_layout в _finalize_msg_step ===
patch(
    ROOT / "handlers/step_create.py",
    '''        "buttons": draft.get("buttons", []),
        "wait_mode": draft.get("wait_mode") or "none",''',
    '''        "buttons": draft.get("buttons", []),
        "buttons_layout": draft.get("buttons_layout") or "grid",
        "wait_mode": draft.get("wait_mode") or "none",''',
    "buttons_layout сохраняется в шаг",
)

# === 2. авто-пропуск ОП не идёт в % ===
patch(
    ROOT / "bots/scenario.py",
    '''        # Если показывать нечего — пропускаем шаг (все обязательные «пройдены»,
        # и необязательных нет).
        if not to_show:
            await get_db().record_step_completion(user["id"], step["id"])
            await self.advance(bot, bot_record, user["id"])
            return -1  # маркер: ничего не отправляем, перешли дальше''',
    '''        # Если показывать нечего — пропускаем шаг (все обязательные «пройдены»,
        # и необязательных нет).
        # ВАЖНО: при авто-пропуске НЕ пишем step_completions — юзер ОП
        # фактически не проходил, иначе % прохождения ОП завышается.
        # advance вызываем — последующие шаги сценария не теряются.
        if not to_show:
            await self.advance(bot, bot_record, user["id"])
            return -1  # маркер: ничего не отправляем, перешли дальше''',
    "авто-пропуск ОП не засчитывается в %",
)

# === 3. чистка pending_join_requests ===
# 3a. добавим метод в DB
DB = ROOT / "database/db.py"
db_src = DB.read_text(encoding="utf-8")
if "cleanup_old_pending" not in db_src:
    anchor = "    async def add_pending_join_request("
    method = '''    async def cleanup_old_pending(self, days: int = 30) -> int:
        """Удаляет заявки старше N дней. Возвращает число удалённых."""
        cutoff = now() - days * 86400
        cur = await self.conn.execute(
            "DELETE FROM pending_join_requests WHERE created_at < ?", (cutoff,)
        )
        await self.conn.commit()
        return cur.rowcount or 0

'''
    db_src = db_src.replace(anchor, method + anchor, 1)
    DB.write_text(db_src, encoding="utf-8")
    print("  ✓ database/db.py — метод cleanup_old_pending")

# 3b. запускаем чистку в sponsor_monitor_loop (он и так раз в 10 мин)
SM = ROOT / "utils/sponsor_monitor.py"
sm_src = SM.read_text(encoding="utf-8")
if "cleanup_old_pending" not in sm_src:
    old_loop = "            bots = await db.list_greeting_bots()"
    new_loop = '''            # Чистим устаревшие заявки, чтобы таблица не пухла
            try:
                _removed = await db.cleanup_old_pending(30)
                if _removed:
                    log.info("Удалено старых заявок: %s", _removed)
            except Exception as _e:
                log.warning("cleanup_old_pending: %s", _e)
            bots = await db.list_greeting_bots()'''
    sm_src = sm_src.replace(old_loop, new_loop, 1)
    SM.write_text(sm_src, encoding="utf-8")
    print("  ✓ utils/sponsor_monitor.py — авто-чистка заявок")

# === 4. разовая чистка БД прямо сейчас + проставить layout старым шагам ===
dbp = "/opt/bot/data.db"
if Path(dbp).exists():
    import time
    conn = sqlite3.connect(dbp)
    cutoff = int(time.time()) - 30 * 86400
    cur = conn.execute("DELETE FROM pending_join_requests WHERE created_at < ?", (cutoff,))
    removed = cur.rowcount or 0
    # старым message-шагам без layout проставим grid (как было по факту)
    fixed = 0
    for sid, cfg_raw in conn.execute("SELECT id, config FROM steps WHERE step_type='message'").fetchall():
        try:
            cfg = json.loads(cfg_raw)
        except Exception:
            continue
        if "buttons_layout" not in cfg:
            cfg["buttons_layout"] = "grid"
            conn.execute("UPDATE steps SET config=? WHERE id=?",
                         (json.dumps(cfg, ensure_ascii=False), sid))
            fixed += 1
    conn.commit()
    conn.close()
    print(f"  ✓ БД: удалено старых заявок {removed}, шагам проставлен layout: {fixed}")

print("\n✅ Патч 15 применён. Перезапусти: systemctl restart bot")
