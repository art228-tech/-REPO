"""БД автопостера v2: основной + помощники + каналы привязаны к помощнику."""
from __future__ import annotations

import time
from typing import Optional

import aiosqlite

_db: Optional["DB"] = None


def now() -> int:
    return int(time.time())


SCHEMA = """
-- Боты-помощники (каждый со своим токеном и polling-ом)
CREATE TABLE IF NOT EXISTS helpers (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    token       TEXT NOT NULL UNIQUE,
    tg_id       INTEGER NOT NULL,
    username    TEXT,
    name        TEXT,
    is_alive    INTEGER NOT NULL DEFAULT 1,   -- 0 = заморожен/удалён
    is_active   INTEGER NOT NULL DEFAULT 1,   -- 0 = polling выключен (для будущих фич)
    last_error  TEXT,
    created_at  INTEGER NOT NULL
);

-- Каналы, привязанные к конкретному помощнику
CREATE TABLE IF NOT EXISTS channels (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    helper_id   INTEGER NOT NULL,
    chat_id     INTEGER NOT NULL,
    title       TEXT NOT NULL,
    username    TEXT,
    created_at  INTEGER NOT NULL,
    UNIQUE(helper_id, chat_id),
    FOREIGN KEY (helper_id) REFERENCES helpers(id) ON DELETE CASCADE
);

-- Общий пул задач (можно использовать на любом канале/помощнике)
CREATE TABLE IF NOT EXISTS tasks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    created_at  INTEGER NOT NULL
);

-- Посты внутри задач
CREATE TABLE IF NOT EXISTS posts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id         INTEGER NOT NULL,
    position        INTEGER NOT NULL DEFAULT 0,
    text            TEXT,
    photo_file_id   TEXT,
    animation_file_id TEXT,
    video_file_id   TEXT,
    document_file_id TEXT,
    sticker_file_id TEXT,
    buttons         TEXT,
    copy_from_chat  INTEGER,
    copy_from_msg   INTEGER,
    next_delay      INTEGER NOT NULL DEFAULT 10,
    delete_after    INTEGER NOT NULL DEFAULT 0,
    created_at      INTEGER NOT NULL,
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
);

-- Состояние постинга на канал
CREATE TABLE IF NOT EXISTS posting_state (
    channel_id      INTEGER PRIMARY KEY,
    is_running      INTEGER NOT NULL DEFAULT 0,
    task_ids        TEXT,
    cur_task_idx    INTEGER NOT NULL DEFAULT 0,
    cur_post_idx    INTEGER NOT NULL DEFAULT 0,
    next_fire_at    INTEGER NOT NULL DEFAULT 0,
    updated_at      INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (channel_id) REFERENCES channels(id) ON DELETE CASCADE
);

-- Запланированные автоудаления (переживает перезапуск)
CREATE TABLE IF NOT EXISTS pending_deletes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    helper_id   INTEGER NOT NULL,
    chat_id     INTEGER NOT NULL,
    message_id  INTEGER NOT NULL,
    fire_at     INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_channels_helper ON channels(helper_id);
CREATE INDEX IF NOT EXISTS idx_posts_task ON posts(task_id, position);
CREATE INDEX IF NOT EXISTS idx_pdel ON pending_deletes(fire_at);
"""


class DB:
    def __init__(self, conn: aiosqlite.Connection):
        self.conn = conn

    # ---------- Помощники ----------
    async def add_helper(self, token: str, tg_id: int, username: str | None,
                         name: str | None) -> int:
        cur = await self.conn.execute(
            "INSERT INTO helpers(token,tg_id,username,name,created_at) "
            "VALUES (?,?,?,?,?)",
            (token, tg_id, username, name, now()),
        )
        await self.conn.commit()
        return cur.lastrowid

    async def list_helpers(self) -> list[aiosqlite.Row]:
        cur = await self.conn.execute("SELECT * FROM helpers ORDER BY id")
        return await cur.fetchall()

    async def list_active_helpers(self) -> list[aiosqlite.Row]:
        cur = await self.conn.execute(
            "SELECT * FROM helpers WHERE is_alive=1 AND is_active=1 ORDER BY id"
        )
        return await cur.fetchall()

    async def get_helper(self, helper_id: int) -> Optional[aiosqlite.Row]:
        cur = await self.conn.execute("SELECT * FROM helpers WHERE id=?", (helper_id,))
        return await cur.fetchone()

    async def get_helper_by_token(self, token: str) -> Optional[aiosqlite.Row]:
        cur = await self.conn.execute("SELECT * FROM helpers WHERE token=?", (token,))
        return await cur.fetchone()

    async def mark_helper_dead(self, helper_id: int, error: str) -> None:
        await self.conn.execute(
            "UPDATE helpers SET is_alive=0, last_error=? WHERE id=?",
            (error, helper_id),
        )
        await self.conn.commit()

    async def mark_helper_alive(self, helper_id: int) -> None:
        await self.conn.execute(
            "UPDATE helpers SET is_alive=1, last_error=NULL WHERE id=?",
            (helper_id,),
        )
        await self.conn.commit()

    async def delete_helper(self, helper_id: int) -> None:
        await self.conn.execute("DELETE FROM helpers WHERE id=?", (helper_id,))
        await self.conn.commit()

    # ---------- Каналы ----------
    async def add_channel(self, helper_id: int, chat_id: int, title: str,
                          username: str | None) -> None:
        await self.conn.execute(
            "INSERT OR IGNORE INTO channels(helper_id,chat_id,title,username,created_at) "
            "VALUES (?,?,?,?,?)",
            (helper_id, chat_id, title, username, now()),
        )
        await self.conn.commit()

    async def list_channels(self, helper_id: int | None = None) -> list[aiosqlite.Row]:
        if helper_id is None:
            cur = await self.conn.execute("SELECT * FROM channels ORDER BY id")
        else:
            cur = await self.conn.execute(
                "SELECT * FROM channels WHERE helper_id=? ORDER BY id", (helper_id,)
            )
        return await cur.fetchall()

    async def get_channel(self, ch_id: int) -> Optional[aiosqlite.Row]:
        cur = await self.conn.execute("SELECT * FROM channels WHERE id=?", (ch_id,))
        return await cur.fetchone()

    async def delete_channel(self, ch_id: int) -> None:
        await self.conn.execute("DELETE FROM channels WHERE id=?", (ch_id,))
        await self.conn.commit()

    # ---------- Задачи ----------
    async def add_task(self, name: str) -> int:
        cur = await self.conn.execute(
            "INSERT INTO tasks(name,created_at) VALUES (?,?)", (name, now())
        )
        await self.conn.commit()
        return cur.lastrowid

    async def list_tasks(self) -> list[aiosqlite.Row]:
        cur = await self.conn.execute("SELECT * FROM tasks ORDER BY id")
        return await cur.fetchall()

    async def get_task(self, task_id: int) -> Optional[aiosqlite.Row]:
        cur = await self.conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,))
        return await cur.fetchone()

    async def rename_task(self, task_id: int, name: str) -> None:
        await self.conn.execute("UPDATE tasks SET name=? WHERE id=?", (name, task_id))
        await self.conn.commit()

    async def delete_task(self, task_id: int) -> None:
        await self.conn.execute("DELETE FROM tasks WHERE id=?", (task_id,))
        # вычищаем удалённую задачу из postings всех каналов
        import json as _j
        cur = await self.conn.execute("SELECT channel_id, task_ids FROM posting_state")
        rows = await cur.fetchall()
        for r in rows:
            try:
                ids = _j.loads(r["task_ids"] or "[]")
            except Exception:
                ids = []
            if task_id in ids:
                ids = [x for x in ids if x != task_id]
                await self.conn.execute(
                    "UPDATE posting_state SET task_ids=? WHERE channel_id=?",
                    (_j.dumps(ids), r["channel_id"]),
                )
        await self.conn.commit()

    # ---------- Посты ----------
    async def add_post(self, task_id: int, cfg: dict) -> int:
        cur = await self.conn.execute(
            "SELECT COALESCE(MAX(position),-1)+1 FROM posts WHERE task_id=?", (task_id,)
        )
        pos = (await cur.fetchone())[0]
        cur = await self.conn.execute(
            "INSERT INTO posts(task_id,position,text,photo_file_id,animation_file_id,"
            "video_file_id,document_file_id,sticker_file_id,buttons,copy_from_chat,"
            "copy_from_msg,next_delay,delete_after,created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                task_id, pos, cfg.get("text"), cfg.get("photo_file_id"),
                cfg.get("animation_file_id"), cfg.get("video_file_id"),
                cfg.get("document_file_id"), cfg.get("sticker_file_id"),
                cfg.get("buttons"), cfg.get("copy_from_chat"), cfg.get("copy_from_msg"),
                int(cfg.get("next_delay", 10)), int(cfg.get("delete_after", 0)), now(),
            ),
        )
        await self.conn.commit()
        return cur.lastrowid

    async def list_posts(self, task_id: int) -> list[aiosqlite.Row]:
        cur = await self.conn.execute(
            "SELECT * FROM posts WHERE task_id=? ORDER BY position", (task_id,)
        )
        return await cur.fetchall()

    async def get_post(self, post_id: int) -> Optional[aiosqlite.Row]:
        cur = await self.conn.execute("SELECT * FROM posts WHERE id=?", (post_id,))
        return await cur.fetchone()

    async def delete_post(self, post_id: int) -> None:
        await self.conn.execute("DELETE FROM posts WHERE id=?", (post_id,))
        await self.conn.commit()

    async def swap_post_positions(self, post_a: int, post_b: int) -> None:
        a = await self.get_post(post_a)
        b = await self.get_post(post_b)
        if not a or not b:
            return
        await self.conn.execute(
            "UPDATE posts SET position=? WHERE id=?", (b["position"], post_a)
        )
        await self.conn.execute(
            "UPDATE posts SET position=? WHERE id=?", (a["position"], post_b)
        )
        await self.conn.commit()

    # ---------- Состояние постинга ----------
    async def get_posting_state(self, channel_id: int) -> Optional[aiosqlite.Row]:
        cur = await self.conn.execute(
            "SELECT * FROM posting_state WHERE channel_id=?", (channel_id,)
        )
        return await cur.fetchone()

    async def set_posting_state(self, channel_id: int, **fields) -> None:
        existing = await self.get_posting_state(channel_id)
        fields["updated_at"] = now()
        if existing:
            sets = ", ".join(f"{k}=?" for k in fields)
            await self.conn.execute(
                f"UPDATE posting_state SET {sets} WHERE channel_id=?",
                list(fields.values()) + [channel_id],
            )
        else:
            fields["channel_id"] = channel_id
            cols = ",".join(fields)
            ph = ",".join("?" * len(fields))
            await self.conn.execute(
                f"INSERT INTO posting_state({cols}) VALUES ({ph})",
                list(fields.values()),
            )
        await self.conn.commit()

    async def all_running_states(self) -> list[aiosqlite.Row]:
        cur = await self.conn.execute("SELECT * FROM posting_state WHERE is_running=1")
        return await cur.fetchall()

    # ---------- Автоудаление ----------
    async def add_pending_delete(self, helper_id: int, chat_id: int,
                                 message_id: int, fire_at: int) -> None:
        await self.conn.execute(
            "INSERT INTO pending_deletes(helper_id,chat_id,message_id,fire_at) "
            "VALUES (?,?,?,?)",
            (helper_id, chat_id, message_id, fire_at),
        )
        await self.conn.commit()

    async def due_pending_deletes(self, ts: int) -> list[aiosqlite.Row]:
        cur = await self.conn.execute(
            "SELECT * FROM pending_deletes WHERE fire_at<=?", (ts,)
        )
        return await cur.fetchall()

    async def remove_pending_delete(self, pd_id: int) -> None:
        await self.conn.execute("DELETE FROM pending_deletes WHERE id=?", (pd_id,))
        await self.conn.commit()


async def init_db(path: str) -> None:
    global _db
    conn = await aiosqlite.connect(path)
    conn.row_factory = aiosqlite.Row
    await conn.executescript(SCHEMA)
    await conn.commit()
    _db = DB(conn)


def get_db() -> DB:
    if _db is None:
        raise RuntimeError("DB не инициализирована")
    return _db
