"""Слой работы с БД (SQLite через aiosqlite).

Статусы чата (status):
    queue         — в очереди на проверку (стартовые/обнаруженные чаты)
    op_unchecked  — канал из списка ОП, ещё не проверен (тоже берётся в работу)
    op_checked    — у чата была ОП, его список ОП обработан
    captcha       — в чате капча/антибот -> "плохая база"
    unrestricted  — без ограничений и участников >= MIN_MEMBERS -> "хорошая база"
    small         — без ограничений, но участников меньше лимита
    error         — не удалось проверить (нет доступа и т.п.)
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

import aiosqlite

# Статусы, которые краулер должен обрабатывать в обычном режиме.
PENDING_STATUSES = ("queue", "op_unchecked")

# Человекочитаемые названия баз для бота.
STATUS_TITLES = {
    "queue": "В очереди",
    "op_unchecked": "ОП непроверенные",
    "op_checked": "ОП проверенные",
    "captcha": "Плохая база (капча)",
    "unrestricted": "Без ограничений",
    "small": "Мало участников (<лимита)",
    "error": "Ошибки доступа",
}


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._db: Optional[aiosqlite.Connection] = None

    async def connect(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self.path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL;")
        await self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS chats (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                ident       TEXT UNIQUE NOT NULL,
                link        TEXT,
                title       TEXT,
                chat_id     INTEGER,
                members     INTEGER DEFAULT 0,
                status      TEXT NOT NULL DEFAULT 'queue',
                source      TEXT,
                reason      TEXT,
                created_at  INTEGER NOT NULL,
                updated_at  INTEGER NOT NULL
            )
            """
        )
        await self._db.execute(
            "CREATE INDEX IF NOT EXISTS idx_chats_status ON chats(status)"
        )
        await self._db.commit()

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    @property
    def db(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("Database is not connected")
        return self._db

    async def add_chat(
        self,
        ident: str,
        link: str,
        *,
        status: str = "queue",
        source: Optional[str] = None,
    ) -> bool:
        """Добавляет чат если его ещё нет. Возвращает True, если добавлен."""
        now = int(time.time())
        cur = await self.db.execute(
            """
            INSERT OR IGNORE INTO chats (ident, link, status, source, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (ident, link, status, source, now, now),
        )
        await self.db.commit()
        return cur.rowcount > 0

    async def exists(self, ident: str) -> bool:
        cur = await self.db.execute("SELECT 1 FROM chats WHERE ident = ?", (ident,))
        return (await cur.fetchone()) is not None

    async def get(self, ident: str) -> Optional[aiosqlite.Row]:
        cur = await self.db.execute("SELECT * FROM chats WHERE ident = ?", (ident,))
        return await cur.fetchone()

    async def next_pending(self) -> Optional[aiosqlite.Row]:
        placeholders = ",".join("?" for _ in PENDING_STATUSES)
        cur = await self.db.execute(
            f"SELECT * FROM chats WHERE status IN ({placeholders}) "
            f"ORDER BY created_at ASC, id ASC LIMIT 1",
            PENDING_STATUSES,
        )
        return await cur.fetchone()

    async def update_status(
        self,
        ident: str,
        status: str,
        *,
        title: Optional[str] = None,
        chat_id: Optional[int] = None,
        members: Optional[int] = None,
        reason: Optional[str] = None,
    ) -> None:
        now = int(time.time())
        fields = ["status = ?", "updated_at = ?"]
        values: list = [status, now]
        if title is not None:
            fields.append("title = ?")
            values.append(title)
        if chat_id is not None:
            fields.append("chat_id = ?")
            values.append(chat_id)
        if members is not None:
            fields.append("members = ?")
            values.append(members)
        if reason is not None:
            fields.append("reason = ?")
            values.append(reason)
        values.append(ident)
        await self.db.execute(
            f"UPDATE chats SET {', '.join(fields)} WHERE ident = ?", values
        )
        await self.db.commit()

    async def list_by_status(
        self, status: str, *, limit: int = 50, offset: int = 0
    ) -> list[aiosqlite.Row]:
        cur = await self.db.execute(
            "SELECT * FROM chats WHERE status = ? ORDER BY members DESC, updated_at DESC "
            "LIMIT ? OFFSET ?",
            (status, limit, offset),
        )
        return await cur.fetchall()

    async def idents_by_status(self, status: str) -> list[str]:
        cur = await self.db.execute(
            "SELECT ident FROM chats WHERE status = ? ORDER BY updated_at DESC",
            (status,),
        )
        return [row["ident"] for row in await cur.fetchall()]

    async def count_by_status(self) -> dict[str, int]:
        cur = await self.db.execute(
            "SELECT status, COUNT(*) AS c FROM chats GROUP BY status"
        )
        return {row["status"]: row["c"] for row in await cur.fetchall()}

    async def pending_count(self) -> int:
        placeholders = ",".join("?" for _ in PENDING_STATUSES)
        cur = await self.db.execute(
            f"SELECT COUNT(*) AS c FROM chats WHERE status IN ({placeholders})",
            PENDING_STATUSES,
        )
        row = await cur.fetchone()
        return row["c"] if row else 0
