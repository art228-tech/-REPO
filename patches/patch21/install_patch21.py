#!/usr/bin/env python3
"""
Патч 21: разбивка воронки в статистике.
- bot_users.source — откуда юзер: 'start' (нажал /start) или 'request'
  (подал заявку в канал).
- bot_users.joined_channel — реально вступил в канал (0/1).
- В разделе «Статистика» сверху — строки воронки:
  нажали /start | подали заявку | вступили в канал.
"""
import sqlite3
from pathlib import Path

ROOT = Path("/opt/bot")  # для друга — /opt/friend_bot


def patch(path: Path, old: str, new: str, label: str):
    src = path.read_text(encoding="utf-8")
    if old not in src:
        raise SystemExit(f"NOT FOUND ({label}) in {path.name}:\n---\n{old[:300]}\n---")
    src = src.replace(old, new, 1)
    path.write_text(src, encoding="utf-8")
    print(f"  ✓ {path.relative_to(ROOT)} — {label}")


# === 1. БД: колонки source и joined_channel ===
DB = ROOT / "database/db.py"
db_src = DB.read_text(encoding="utf-8")
if "joined_channel" not in db_src:
    db_src = db_src.replace(
        "    ref_link_id         INTEGER,",
        "    ref_link_id         INTEGER,\n"
        "    source              TEXT DEFAULT 'start',\n"
        "    joined_channel      INTEGER DEFAULT 0,",
        1,
    )
    DB.write_text(db_src, encoding="utf-8")
    print("  ✓ database/db.py — колонки source/joined_channel в схеме")

# миграция
dbp = str(ROOT / "data.db")
if Path(dbp).exists():
    conn = sqlite3.connect(dbp)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(bot_users)").fetchall()]
    if "source" not in cols:
        conn.execute("ALTER TABLE bot_users ADD COLUMN source TEXT DEFAULT 'start'")
        print("  ✓ data.db — колонка source")
    if "joined_channel" not in cols:
        conn.execute("ALTER TABLE bot_users ADD COLUMN joined_channel INTEGER DEFAULT 0")
        print("  ✓ data.db — колонка joined_channel")
    conn.commit()
    conn.close()

# === 2. upsert_user: принимать source ===
db_src = DB.read_text(encoding="utf-8")
if "source: str" not in db_src:
    patch(
        DB,
        '''        is_premium: bool = False,
        ref_link_id: int | None = None,
    ) -> aiosqlite.Row:''',
        '''        is_premium: bool = False,
        ref_link_id: int | None = None,
        source: str = "start",
    ) -> aiosqlite.Row:''',
        "upsert_user принимает source",
    )
    # INSERT — добавляем source
    patch(
        DB,
        '''        cur = await self.conn.execute(
            "INSERT INTO bot_users "
            "(bot_id, tg_id, username, first_name, is_premium, ref_link_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (bot_id, tg_id, username, first_name, int(is_premium), ref_link_id, now()),
        )''',
        '''        cur = await self.conn.execute(
            "INSERT INTO bot_users "
            "(bot_id, tg_id, username, first_name, is_premium, ref_link_id, source, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (bot_id, tg_id, username, first_name, int(is_premium), ref_link_id, source, now()),
        )''',
        "INSERT с source",
    )

# === 3. метод mark_joined_channel ===
db_src = DB.read_text(encoding="utf-8")
if "mark_joined_channel" not in db_src:
    idx = db_src.find("    async def get_user(self")
    method = (
        "    async def mark_joined_channel(self, bot_id: int, tg_id: int):\n"
        '        """Помечает, что юзер реально вступил в канал."""\n'
        "        await self.conn.execute(\n"
        '            "UPDATE bot_users SET joined_channel=1 WHERE bot_id=? AND tg_id=?",\n'
        "            (bot_id, tg_id),\n"
        "        )\n"
        "        await self.conn.commit()\n"
        "\n"
    )
    db_src = db_src[:idx] + method + db_src[idx:]
    DB.write_text(db_src, encoding="utf-8")
    print("  ✓ database/db.py — метод mark_joined_channel")

# === 4. greeter.py: source='request' для заявок ===
GR = ROOT / "bots/greeter.py"
gr_src = GR.read_text(encoding="utf-8")
if 'source="request"' not in gr_src:
    patch(
        GR,
        '''        user = await db.upsert_user(
            bot_record["id"],
            req.from_user.id,
            username=req.from_user.username,
            first_name=req.from_user.first_name,
            is_premium=bool(getattr(req.from_user, "is_premium", False)),
        )''',
        '''        user = await db.upsert_user(
            bot_record["id"],
            req.from_user.id,
            username=req.from_user.username,
            first_name=req.from_user.first_name,
            is_premium=bool(getattr(req.from_user, "is_premium", False)),
            source="request",
        )''',
        "source=request в on_join_request",
    )

# 4b. on_chat_member: помечаем вступление в канал
if "mark_joined_channel" not in gr_src:
    gr_src = GR.read_text(encoding="utf-8")
    patch(
        GR,
        '''            # вступил: был left/kicked → стал member
            if new_s == "member" and old_s in ("left", "kicked", None):
                await db.inc_channel_link(il.invite_link, joined=1)''',
        '''            # вступил: был left/kicked → стал member
            if new_s == "member" and old_s in ("left", "kicked", None):
                await db.inc_channel_link(il.invite_link, joined=1)
                try:
                    await db.mark_joined_channel(
                        bot_record["id"], upd.from_user.id
                    )
                except Exception as _e:
                    log.warning("mark_joined_channel: %s", _e)''',
        "отметка вступления в канал",
    )

# === 5. stats.py: воронка источников в начале статистики ===
ST = ROOT / "handlers/stats.py"
st_src = ST.read_text(encoding="utf-8")
if "Воронка" not in st_src:
    # Вставляем после строки "🟢 Живых". Найдём блок формирования общего текста.
    patch(
        ST,
        '''        f"🏁 Полностью прошли сценарий: {n_completed} ({n_completed*100//total}%)\\n"''',
        '''        f"🏁 Полностью прошли сценарий: {n_completed} ({n_completed*100//total}%)\\n"
        + (
            "\\n<b>🧭 Воронка:</b>\\n"
            f"  ▶️ Нажали /start: {sum(1 for u in users_f if (u['source'] or 'start')=='start')}\\n"
            f"  ✋ Подали заявку: {sum(1 for u in users_f if (u['source'] or 'start')=='request')}\\n"
            f"  ✅ Вступили в канал: {sum(1 for u in users_f if u['joined_channel'])}\\n"
        )''',
        "воронка источников в статистике",
    )

print("\\n✅ Патч 21 применён. Перезапусти бот.")
