"""Lightweight SQLite-backed storage for known users.

Uses the standard-library ``sqlite3`` module. Blocking calls are wrapped in
``asyncio.to_thread`` so they don't stall the event loop.
"""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from typing import Iterable


class UserStorage:
    """Persists the set of users that have interacted with the bot."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_sync(self) -> None:
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id     INTEGER PRIMARY KEY,
                    username    TEXT,
                    full_name   TEXT,
                    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
                )
                """
            )
            conn.commit()

    async def init(self) -> None:
        await asyncio.to_thread(self._init_sync)

    def _upsert_sync(self, user_id: int, username: str | None, full_name: str | None) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO users (user_id, username, full_name)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    username = excluded.username,
                    full_name = excluded.full_name
                """,
                (user_id, username, full_name),
            )
            conn.commit()

    async def upsert_user(
        self, user_id: int, username: str | None, full_name: str | None
    ) -> None:
        await asyncio.to_thread(self._upsert_sync, user_id, username, full_name)

    def _all_user_ids_sync(self) -> list[int]:
        with self._connect() as conn:
            rows = conn.execute("SELECT user_id FROM users").fetchall()
        return [int(row["user_id"]) for row in rows]

    async def all_user_ids(self) -> list[int]:
        return await asyncio.to_thread(self._all_user_ids_sync)

    def _count_sync(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()
        return int(row["c"]) if row else 0

    async def count_users(self) -> int:
        return await asyncio.to_thread(self._count_sync)


def chunked(items: list[int], size: int) -> Iterable[list[int]]:
    """Yield successive chunks of ``size`` from ``items``."""
    for start in range(0, len(items), size):
        yield items[start : start + size]
