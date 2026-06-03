"""Асинхронная БД автопостера (SQLite/aiosqlite)."""
from __future__ import annotations

import time
from typing import Optional

import aiosqlite

_db: Optional["DB"] = None


def now() -> int:
    return int(time.time())


SCHEMA = """
-- Каналы, куда постим (бот — админ с правами публикации/удаления)
CREATE TABLE IF NOT EXISTS channels (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id     INTEGER NOT NULL UNIQUE,
    title       TEXT NOT NULL,
    username    TEXT,
    created_at  INTEGER NOT NULL
);

-- Задачи — контейнеры постов
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
    -- контент: либо собственный (text/media/buttons), либо копия поста
    text            TEXT,
    photo_file_id   TEXT,
    animation_file_id TEXT,
    video_file_id   TEXT,
    document_file_id TEXT,
    sticker_file_id TEXT,
    buttons         TEXT,          -- JSON: список кнопок
    copy_from_chat  INTEGER,       -- если пост — копия: откуда
    copy_from_msg   INTEGER,
    next_delay      INTEGER NOT NULL DEFAULT 10,   -- сек до следующего поста
    delete_after    INTEGER NOT NULL DEFAULT 0,    -- сек до автоудаления (0 = не удалять)
    created_at      INTEGER NOT NULL,
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
);

-- Состояние автопостинга (один канал = одна запись)
CREATE TABLE IF NOT EXISTS posting_state (
    channel_id      INTEGER PRIMARY KEY,   -- channels.id
    is_running      INTEGER NOT NULL DEFAULT 0,
    task_ids        TEXT,                  -- JSON: выбранные задачи по порядку
    cur_task_idx    INTEGER NOT NULL DEFAULT 0,
    cur_post_idx    INTEGER NOT NULL DEFAULT 0,
    next_fire_at    INTEGER NOT NULL DEFAULT 0,
    updated_at      INTEGER NOT NULL DEFAULT 0
);

-- Запланированные автоудаления постов (переживает перезапуск)
CREATE TABLE IF NOT EXISTS pending_deletes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id     INTEGER NOT NULL,
    message_id  INTEGER NOT NULL,
    fire_at     INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_posts_task ON posts(task_id, position);
CREATE INDEX IF NOT EXISTS idx_pdel ON pending_deletes(fire_at);
"""


class DB:
    def __init__(self, conn: aiosqlite.Connection):
        self.conn = conn

    # ---------- Каналы ----------
    async def add_channel(self, chat_id: int, title: str, username: str | None) -> None:
        await self.conn.execute(
            "INSERT OR IGNORE INTO channels(chat_id,title,username,created_at) "
            "VALUES (?,?,?,?)",
            (chat_id, title, username, now()),
        )
        await self.conn.commit()

    async def list_channels(self) -> list[aiosqlite.Row]:
        cur = await self.conn.execute("SELECT * FROM channels ORDER BY id")
        return await cur.fetchall()

    async def get_channel(self, ch_id: int) -> Optional[aiosqlite.Row]:
        cur = await self.conn.execute("SELECT * FROM channels WHERE id=?", (ch_id,))
        return await cur.fetchone()

    async def delete_channel(self, ch_id: int) -> None:
        await self.conn.execute("DELETE FROM channels WHERE id=?", (ch_id,))
        await self.conn.execute("DELETE FROM posting_state WHERE channel_id=?", (ch_id,))
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
        await self.conn.commit()

    # ---------- Посты ----------
    async def add_post(self, task_id: int, cfg: dict) -> int:
        cur = await self.conn.execute("SELECT COALESCE(MAX(position),-1)+1 FROM posts WHERE task_id=?", (task_id,))
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

    async def update_post(self, post_id: int, **fields) -> None:
        if not fields:
            return
        sets = ", ".join(f"{k}=?" for k in fields)
        params = list(fields.values()) + [post_id]
        await self.conn.execute(f"UPDATE posts SET {sets} WHERE id=?", params)
        await self.conn.commit()

    async def swap_post_positions(self, post_a: int, post_b: int) -> None:
        a = await self.get_post(post_a)
        b = await self.get_post(post_b)
        if not a or not b:
            return
        await self.conn.execute("UPDATE posts SET position=? WHERE id=?", (b["position"], post_a))
        await self.conn.execute("UPDATE posts SET position=? WHERE id=?", (a["position"], post_b))
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
                f"INSERT INTO posting_state({cols}) VALUES ({ph})", list(fields.values())
            )
        await self.conn.commit()

    async def all_running_states(self) -> list[aiosqlite.Row]:
        cur = await self.conn.execute("SELECT * FROM posting_state WHERE is_running=1")
        return await cur.fetchall()

    # ---------- Автоудаление ----------
    async def add_pending_delete(self, chat_id: int, message_id: int, fire_at: int) -> None:
        await self.conn.execute(
            "INSERT INTO pending_deletes(chat_id,message_id,fire_at) VALUES (?,?,?)",
            (chat_id, message_id, fire_at),
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
