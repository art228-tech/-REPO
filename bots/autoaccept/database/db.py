"""БД автоприёма v2: помощники + каналы (с настройками автоприёма) + очередь."""
from __future__ import annotations

import time
from typing import Optional

import aiosqlite

_db: Optional["DB"] = None


def now() -> int:
    return int(time.time())


SCHEMA = """
-- Боты-помощники
CREATE TABLE IF NOT EXISTS helpers (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    token       TEXT NOT NULL UNIQUE,
    tg_id       INTEGER NOT NULL,
    username    TEXT,
    name        TEXT,
    is_alive    INTEGER NOT NULL DEFAULT 1,
    is_active   INTEGER NOT NULL DEFAULT 1,
    last_error  TEXT,
    created_at  INTEGER NOT NULL
);

-- Каналы (привязаны к помощнику + настройки автоприёма)
CREATE TABLE IF NOT EXISTS channels (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    helper_id       INTEGER NOT NULL,
    chat_id         INTEGER NOT NULL,
    title           TEXT NOT NULL,
    username        TEXT,
    auto_accept     INTEGER NOT NULL DEFAULT 1,   -- 1 = включён автоприём
    accept_delay    INTEGER NOT NULL DEFAULT 0,   -- секунд до приёма
    created_at      INTEGER NOT NULL,
    UNIQUE(helper_id, chat_id),
    FOREIGN KEY (helper_id) REFERENCES helpers(id) ON DELETE CASCADE
);

-- Очередь заявок к приёму (переживает перезапуск)
CREATE TABLE IF NOT EXISTS pending_accepts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    helper_id   INTEGER NOT NULL,
    channel_id  INTEGER NOT NULL,   -- channels.id
    chat_id     INTEGER NOT NULL,   -- Telegram chat_id
    user_id     INTEGER NOT NULL,
    fire_at     INTEGER NOT NULL,
    created_at  INTEGER NOT NULL,
    UNIQUE(helper_id, chat_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_channels_helper ON channels(helper_id);
CREATE INDEX IF NOT EXISTS idx_pending_fire ON pending_accepts(fire_at);
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

    async def get_helper_by_tg_id(self, tg_id: int) -> Optional[aiosqlite.Row]:
        cur = await self.conn.execute("SELECT * FROM helpers WHERE tg_id=?", (tg_id,))
        return await cur.fetchone()

    async def mark_helper_dead(self, helper_id: int, error: str) -> None:
        await self.conn.execute(
            "UPDATE helpers SET is_alive=0, last_error=? WHERE id=?",
            (error, helper_id),
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

    async def get_channel_by_chat(self, helper_id: int,
                                  chat_id: int) -> Optional[aiosqlite.Row]:
        cur = await self.conn.execute(
            "SELECT * FROM channels WHERE helper_id=? AND chat_id=?",
            (helper_id, chat_id),
        )
        return await cur.fetchone()

    async def set_channel_auto_accept(self, ch_id: int, on: int) -> None:
        await self.conn.execute(
            "UPDATE channels SET auto_accept=? WHERE id=?", (on, ch_id)
        )
        await self.conn.commit()

    async def set_channel_delay(self, ch_id: int, delay: int) -> None:
        await self.conn.execute(
            "UPDATE channels SET accept_delay=? WHERE id=?", (int(delay), ch_id)
        )
        await self.conn.commit()

    async def delete_channel(self, ch_id: int) -> None:
        await self.conn.execute("DELETE FROM channels WHERE id=?", (ch_id,))
        await self.conn.commit()

    # ---------- Очередь приёма ----------
    async def schedule_accept(self, helper_id: int, channel_id: int,
                              chat_id: int, user_id: int, fire_at: int) -> None:
        await self.conn.execute(
            "INSERT OR REPLACE INTO pending_accepts"
            "(helper_id,channel_id,chat_id,user_id,fire_at,created_at) "
            "VALUES (?,?,?,?,?,?)",
            (helper_id, channel_id, chat_id, user_id, fire_at, now()),
        )
        await self.conn.commit()

    async def due_accepts(self, ts: int) -> list[aiosqlite.Row]:
        cur = await self.conn.execute(
            "SELECT * FROM pending_accepts WHERE fire_at<=? ORDER BY fire_at LIMIT 100",
            (ts,),
        )
        return await cur.fetchall()

    async def remove_pending_accept(self, pa_id: int) -> None:
        await self.conn.execute("DELETE FROM pending_accepts WHERE id=?", (pa_id,))
        await self.conn.commit()

    async def count_pending_accepts(self, channel_id: int) -> int:
        cur = await self.conn.execute(
            "SELECT COUNT(*) FROM pending_accepts WHERE channel_id=?", (channel_id,)
        )
        return (await cur.fetchone())[0]


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
