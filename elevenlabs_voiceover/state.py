"""Локальная база прогресса.

Решает три задачи: не платить дважды за уже озвученный кусок, продолжать работу
после сбоя с того же места и помнить созданные голоса, чтобы не тратить на них
кредиты и слоты при каждом запуске.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from .logging_setup import get_logger
from .paths import state_db_path

log = get_logger("state")

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS voices (
    prompt_key         TEXT PRIMARY KEY,
    prompt_file        TEXT NOT NULL,
    voice_id           TEXT NOT NULL,
    voice_name         TEXT NOT NULL,
    description        TEXT NOT NULL,
    generated_voice_id TEXT,
    preview_path       TEXT,
    created_at         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chunks (
    task_key    TEXT PRIMARY KEY,
    text_file   TEXT NOT NULL,
    voice_id    TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    characters  INTEGER NOT NULL,
    status      TEXT NOT NULL,
    audio_path  TEXT,
    request_id  TEXT,
    error       TEXT,
    updated_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_chunks_file ON chunks (text_file, voice_id);

CREATE TABLE IF NOT EXISTS outputs (
    output_key  TEXT PRIMARY KEY,
    text_file   TEXT NOT NULL,
    voice_id    TEXT NOT NULL,
    voice_name  TEXT NOT NULL,
    output_path TEXT NOT NULL,
    characters  INTEGER NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS usage_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         TEXT NOT NULL,
    kind       TEXT NOT NULL,
    characters INTEGER NOT NULL,
    voice_id   TEXT,
    note       TEXT
);

CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    outcome     TEXT,
    stats       TEXT
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def digest(*parts: Any) -> str:
    hasher = hashlib.sha256()
    for part in parts:
        hasher.update(str(part).encode("utf-8"))
        hasher.update(b"\x1f")
    return hasher.hexdigest()[:32]


@dataclass
class StoredVoice:
    prompt_key: str
    prompt_file: str
    voice_id: str
    voice_name: str
    description: str
    generated_voice_id: Optional[str] = None
    preview_path: Optional[str] = None


class StateStore:
    def __init__(self, path: Optional[Path] = None) -> None:
        self._path = path or state_db_path()
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.execute(
                "INSERT INTO meta (key, value) VALUES ('schema_version', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (str(SCHEMA_VERSION),),
            )
            self._conn.commit()
        log.debug("База прогресса открыта: %s", self._path)

    @property
    def path(self) -> Path:
        return self._path

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except Exception:  # noqa: BLE001
                pass

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            try:
                yield self._conn
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    # ------------------------------------------------------------------
    # Голоса
    # ------------------------------------------------------------------
    def get_voice(self, prompt_key: str) -> Optional[StoredVoice]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM voices WHERE prompt_key = ?", (prompt_key,)
            ).fetchone()
        if not row:
            return None
        return StoredVoice(
            prompt_key=row["prompt_key"],
            prompt_file=row["prompt_file"],
            voice_id=row["voice_id"],
            voice_name=row["voice_name"],
            description=row["description"],
            generated_voice_id=row["generated_voice_id"],
            preview_path=row["preview_path"],
        )

    def save_voice(self, voice: StoredVoice) -> None:
        with self._write() as conn:
            conn.execute(
                """
                INSERT INTO voices (prompt_key, prompt_file, voice_id, voice_name,
                                    description, generated_voice_id, preview_path, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(prompt_key) DO UPDATE SET
                    prompt_file        = excluded.prompt_file,
                    voice_id           = excluded.voice_id,
                    voice_name         = excluded.voice_name,
                    description        = excluded.description,
                    generated_voice_id = excluded.generated_voice_id,
                    preview_path       = excluded.preview_path
                """,
                (
                    voice.prompt_key,
                    voice.prompt_file,
                    voice.voice_id,
                    voice.voice_name,
                    voice.description,
                    voice.generated_voice_id,
                    voice.preview_path,
                    _now(),
                ),
            )

    def forget_voice(self, prompt_key: str) -> None:
        with self._write() as conn:
            conn.execute("DELETE FROM voices WHERE prompt_key = ?", (prompt_key,))

    def all_voices(self) -> List[StoredVoice]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM voices ORDER BY created_at").fetchall()
        return [
            StoredVoice(
                prompt_key=r["prompt_key"],
                prompt_file=r["prompt_file"],
                voice_id=r["voice_id"],
                voice_name=r["voice_name"],
                description=r["description"],
                generated_voice_id=r["generated_voice_id"],
                preview_path=r["preview_path"],
            )
            for r in rows
        ]

    # ------------------------------------------------------------------
    # Куски
    # ------------------------------------------------------------------
    def get_chunk(self, task_key: str) -> Optional[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(
                "SELECT * FROM chunks WHERE task_key = ?", (task_key,)
            ).fetchone()

    def chunk_is_done(self, task_key: str) -> Optional[str]:
        """Вернуть путь к готовому куску, если он существует на диске."""
        row = self.get_chunk(task_key)
        if not row or row["status"] != "done":
            return None
        path = row["audio_path"]
        if path and Path(path).exists():
            return path
        # Запись есть, файла нет — считаем кусок незавершённым.
        return None

    def mark_chunk_done(
        self,
        task_key: str,
        *,
        text_file: str,
        voice_id: str,
        chunk_index: int,
        characters: int,
        audio_path: str,
        request_id: Optional[str],
    ) -> None:
        with self._write() as conn:
            conn.execute(
                """
                INSERT INTO chunks (task_key, text_file, voice_id, chunk_index, characters,
                                    status, audio_path, request_id, error, updated_at)
                VALUES (?, ?, ?, ?, ?, 'done', ?, ?, NULL, ?)
                ON CONFLICT(task_key) DO UPDATE SET
                    status     = 'done',
                    audio_path = excluded.audio_path,
                    request_id = excluded.request_id,
                    characters = excluded.characters,
                    error      = NULL,
                    updated_at = excluded.updated_at
                """,
                (task_key, text_file, voice_id, chunk_index, characters, audio_path, request_id, _now()),
            )

    def mark_chunk_failed(
        self,
        task_key: str,
        *,
        text_file: str,
        voice_id: str,
        chunk_index: int,
        characters: int,
        error: str,
    ) -> None:
        with self._write() as conn:
            conn.execute(
                """
                INSERT INTO chunks (task_key, text_file, voice_id, chunk_index, characters,
                                    status, audio_path, request_id, error, updated_at)
                VALUES (?, ?, ?, ?, ?, 'failed', NULL, NULL, ?, ?)
                ON CONFLICT(task_key) DO UPDATE SET
                    status     = 'failed',
                    error      = excluded.error,
                    updated_at = excluded.updated_at
                """,
                (task_key, text_file, voice_id, chunk_index, characters, error[:2000], _now()),
            )

    def get_chunk_request_id(self, task_key: str) -> Optional[str]:
        row = self.get_chunk(task_key)
        return row["request_id"] if row else None

    # ------------------------------------------------------------------
    # Готовые файлы
    # ------------------------------------------------------------------
    def output_is_done(self, output_key: str) -> Optional[str]:
        with self._lock:
            row = self._conn.execute(
                "SELECT output_path FROM outputs WHERE output_key = ?", (output_key,)
            ).fetchone()
        if not row:
            return None
        path = row["output_path"]
        return path if path and Path(path).exists() else None

    def mark_output_done(
        self,
        output_key: str,
        *,
        text_file: str,
        voice_id: str,
        voice_name: str,
        output_path: str,
        characters: int,
    ) -> None:
        with self._write() as conn:
            conn.execute(
                """
                INSERT INTO outputs (output_key, text_file, voice_id, voice_name,
                                     output_path, characters, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(output_key) DO UPDATE SET
                    output_path = excluded.output_path,
                    characters  = excluded.characters,
                    created_at  = excluded.created_at
                """,
                (output_key, text_file, voice_id, voice_name, output_path, characters, _now()),
            )

    # ------------------------------------------------------------------
    # Учёт расхода и прогоны
    # ------------------------------------------------------------------
    def log_usage(self, kind: str, characters: int, voice_id: Optional[str] = None, note: str = "") -> None:
        with self._write() as conn:
            conn.execute(
                "INSERT INTO usage_log (ts, kind, characters, voice_id, note) VALUES (?, ?, ?, ?, ?)",
                (_now(), kind, characters, voice_id, note[:500]),
            )

    def start_run(self) -> int:
        with self._write() as conn:
            cursor = conn.execute("INSERT INTO runs (started_at) VALUES (?)", (_now(),))
            return int(cursor.lastrowid or 0)

    def finish_run(self, run_id: int, outcome: str, stats: Dict[str, Any]) -> None:
        with self._write() as conn:
            conn.execute(
                "UPDATE runs SET finished_at = ?, outcome = ?, stats = ? WHERE id = ?",
                (_now(), outcome, json.dumps(stats, ensure_ascii=False), run_id),
            )

    # ------------------------------------------------------------------
    def summary(self) -> Dict[str, Any]:
        with self._lock:
            def scalar(sql: str) -> int:
                row = self._conn.execute(sql).fetchone()
                return int(row[0] or 0) if row else 0

            recent_runs = [
                dict(r)
                for r in self._conn.execute(
                    "SELECT id, started_at, finished_at, outcome, stats FROM runs ORDER BY id DESC LIMIT 10"
                ).fetchall()
            ]
            recent_errors = [
                dict(r)
                for r in self._conn.execute(
                    "SELECT text_file, voice_id, chunk_index, error, updated_at FROM chunks "
                    "WHERE status = 'failed' ORDER BY updated_at DESC LIMIT 30"
                ).fetchall()
            ]

            return {
                "voices": scalar("SELECT COUNT(*) FROM voices"),
                "chunks_done": scalar("SELECT COUNT(*) FROM chunks WHERE status = 'done'"),
                "chunks_failed": scalar("SELECT COUNT(*) FROM chunks WHERE status = 'failed'"),
                "outputs": scalar("SELECT COUNT(*) FROM outputs"),
                "characters_spent": scalar("SELECT SUM(characters) FROM usage_log"),
                "recent_runs": recent_runs,
                "recent_errors": recent_errors,
            }

    def reset_progress(self, *, drop_voices: bool = False) -> None:
        """Забыть прогресс озвучки. Голоса стираются только по явной просьбе."""
        with self._write() as conn:
            conn.execute("DELETE FROM chunks")
            conn.execute("DELETE FROM outputs")
            if drop_voices:
                conn.execute("DELETE FROM voices")
        log.info("Прогресс сброшен (голоса %s)", "стёрты" if drop_voices else "сохранены")
