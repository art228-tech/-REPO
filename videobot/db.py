"""База: люди, ролики, замеры просмотров.

Всё держится в одном файле SQLite рядом с программой. Соединение открывается на
каждую операцию: к базе ходят и окно программы, и бот из своего потока, а
объёмы здесь такие, что экономить на этом нечего — полтора десятка роликов в
день.

Времена хранятся в UTC строками ISO. Не ради красоты: по ним считается возраст
ролика, а местное время дважды в год прыгает на час, и ролик, выложенный в ночь
перевода часов, получил бы возраст на час больше или меньше настоящего.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS people (
    tg_id      INTEGER PRIMARY KEY,
    name       TEXT    NOT NULL DEFAULT '',
    is_admin   INTEGER NOT NULL DEFAULT 0,
    has_access INTEGER NOT NULL DEFAULT 0,
    added_at   TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS videos (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT    NOT NULL UNIQUE,
    file_path    TEXT    NOT NULL DEFAULT '',
    file_id      TEXT    NOT NULL DEFAULT '',
    status       TEXT    NOT NULL,
    error        TEXT    NOT NULL DEFAULT '',
    duration_s   REAL    NOT NULL DEFAULT 0,
    background   TEXT    NOT NULL DEFAULT '',
    voice_folder TEXT    NOT NULL DEFAULT '',
    music        INTEGER NOT NULL DEFAULT 0,
    qr_s         REAL    NOT NULL DEFAULT 0,
    added_at     TEXT    NOT NULL,
    owner_id     INTEGER,
    assigned_at  TEXT,
    taken_at     TEXT,
    reminded_at  TEXT
);

CREATE TABLE IF NOT EXISTS views (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id    INTEGER NOT NULL,
    value       INTEGER NOT NULL,
    measured_at TEXT    NOT NULL,
    FOREIGN KEY (video_id) REFERENCES videos (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS videos_by_owner  ON videos (owner_id, taken_at);
CREATE INDEX IF NOT EXISTS videos_by_status ON videos (status);
CREATE INDEX IF NOT EXISTS views_by_video   ON views  (video_id, measured_at);
"""

PENDING = "pending"
READY = "ready"
FAILED = "failed"


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse(stamp: str | None) -> datetime | None:
    if not stamp:
        return None
    try:
        return datetime.fromisoformat(stamp)
    except ValueError:
        return None


@dataclass
class Video:
    id: int
    name: str
    file_id: str
    duration_s: float
    background: str
    voice_folder: str
    music: bool
    qr_s: float
    owner_id: int | None
    taken_at: str | None


class Base:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, timeout=15)
        conn.row_factory = sqlite3.Row
        # WAL нужен, чтобы окно программы и бот не запирали друг друга: без него
        # заливка ролика блокирует чтение меню, и человек видит зависший бот.
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # --- люди -------------------------------------------------------------

    def remember_person(self, tg_id: int, name: str) -> None:
        """Записывает того, кто нажал «Старт». Доступ при этом не выдаётся."""
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO people (tg_id, name, added_at) VALUES (?, ?, ?) "
                "ON CONFLICT (tg_id) DO UPDATE SET name = excluded.name",
                (tg_id, name, now()),
            )

    def person(self, tg_id: int) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute(
                "SELECT * FROM people WHERE tg_id = ?", (tg_id,)
            ).fetchone()

    def people(self) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return list(conn.execute(
                "SELECT * FROM people ORDER BY is_admin DESC, has_access DESC, added_at"
            ))

    def set_access(self, tg_id: int, allowed: bool) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO people (tg_id, has_access, added_at) VALUES (?, ?, ?) "
                "ON CONFLICT (tg_id) DO UPDATE SET has_access = excluded.has_access",
                (tg_id, int(allowed), now()),
            )

    def make_admin(self, tg_id: int) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO people (tg_id, is_admin, has_access, added_at) "
                "VALUES (?, 1, 1, ?) "
                "ON CONFLICT (tg_id) DO UPDATE SET is_admin = 1, has_access = 1",
                (tg_id, now()),
            )

    def admin_ids(self) -> list[int]:
        with self.connect() as conn:
            return [row["tg_id"] for row in
                    conn.execute("SELECT tg_id FROM people WHERE is_admin = 1")]

    # --- ролики -----------------------------------------------------------

    def add_video(self, name: str, file_path: str, data: dict) -> bool:
        """Ставит ролик в очередь на заливку. False — такой уже есть."""
        with self.connect() as conn:
            try:
                conn.execute(
                    "INSERT INTO videos (name, file_path, status, duration_s, "
                    "background, voice_folder, music, qr_s, added_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (name, file_path, PENDING,
                     float(data.get("duration_s") or 0),
                     str(data.get("background") or ""),
                     str(data.get("voice_folder") or ""),
                     int(bool(data.get("music"))),
                     float(data.get("qr_s") or 0),
                     now()),
                )
            except sqlite3.IntegrityError:
                return False
        return True

    def next_pending(self) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute(
                "SELECT * FROM videos WHERE status = ? ORDER BY id LIMIT 1", (PENDING,)
            ).fetchone()

    def mark_ready(self, video_id: int, file_id: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE videos SET status = ?, file_id = ?, file_path = '', error = '' "
                "WHERE id = ?",
                (READY, file_id, video_id),
            )

    def mark_failed(self, video_id: int, error: str) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE videos SET status = ?, error = ? WHERE id = ?",
                         (FAILED, error, video_id))

    def counts(self) -> dict[str, int]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) AS n FROM videos GROUP BY status")
            by_status = {row["status"]: row["n"] for row in rows}
            free = conn.execute(
                "SELECT COUNT(*) AS n FROM videos WHERE status = ? AND owner_id IS NULL",
                (READY,)).fetchone()["n"]
        return {
            "pending": by_status.get(PENDING, 0),
            "ready": by_status.get(READY, 0),
            "failed": by_status.get(FAILED, 0),
            "free": free,
        }

    def assign(self, owner_id: int, count: int) -> int:
        """Отдаёт человеку `count` самых старых свободных роликов."""
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT id FROM videos WHERE status = ? AND owner_id IS NULL "
                "ORDER BY id LIMIT ?", (READY, count)).fetchall()
            if not rows:
                return 0
            stamp = now()
            conn.executemany(
                "UPDATE videos SET owner_id = ?, assigned_at = ? WHERE id = ?",
                [(owner_id, stamp, row["id"]) for row in rows])
        return len(rows)

    def take_back(self, owner_id: int) -> int:
        """Забирает у человека всё, что он ещё не скачал."""
        with self.connect() as conn:
            cursor = conn.execute(
                "UPDATE videos SET owner_id = NULL, assigned_at = NULL "
                "WHERE owner_id = ? AND taken_at IS NULL", (owner_id,))
        return cursor.rowcount

    def waiting_for(self, owner_id: int) -> int:
        with self.connect() as conn:
            return conn.execute(
                "SELECT COUNT(*) AS n FROM videos "
                "WHERE owner_id = ? AND taken_at IS NULL", (owner_id,)).fetchone()["n"]

    def next_to_hand_over(self, owner_id: int, limit: int) -> list[Video]:
        """Что выдать человеку: по хронологии, самые старые первыми."""
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM videos WHERE owner_id = ? AND taken_at IS NULL "
                "ORDER BY id LIMIT ?", (owner_id, limit)).fetchall()
        return [_video(row) for row in rows]

    def mark_taken(self, video_id: int) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE videos SET taken_at = ? WHERE id = ? AND taken_at IS NULL",
                         (now(), video_id))

    def history(self, owner_id: int, limit: int = 50) -> list[sqlite3.Row]:
        """Скачанные ролики с последним замером просмотров."""
        with self.connect() as conn:
            return list(conn.execute(
                "SELECT v.*, ("
                "  SELECT value FROM views w WHERE w.video_id = v.id "
                "  ORDER BY w.measured_at DESC, w.id DESC LIMIT 1"
                ") AS last_views "
                "FROM videos v WHERE v.owner_id = ? AND v.taken_at IS NOT NULL "
                "ORDER BY v.taken_at DESC LIMIT ?", (owner_id, limit)))

    def video(self, video_id: int) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute("SELECT * FROM videos WHERE id = ?", (video_id,)).fetchone()

    # --- просмотры --------------------------------------------------------

    def add_views(self, video_id: int, value: int) -> None:
        """Ещё один замер. Прежние остаются: ролик набирает просмотры со временем."""
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO views (video_id, value, measured_at) VALUES (?, ?, ?)",
                (video_id, value, now()))

    def due_for_reminder(self, hours: int) -> list[sqlite3.Row]:
        """Скачанные больше суток назад, без просмотров и без напоминания."""
        border = datetime.now(timezone.utc).timestamp() - hours * 3600
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM videos WHERE taken_at IS NOT NULL AND reminded_at IS NULL "
                "AND NOT EXISTS (SELECT 1 FROM views w WHERE w.video_id = videos.id)"
            ).fetchall()
        due = []
        for row in rows:
            taken = parse(row["taken_at"])
            if taken and taken.timestamp() <= border:
                due.append(row)
        return due

    def mark_reminded(self, video_id: int) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE videos SET reminded_at = ? WHERE id = ?", (now(), video_id))

    def measured(self) -> list[sqlite3.Row]:
        """Ролики с просмотрами — то, на чём считается статистика."""
        with self.connect() as conn:
            return list(conn.execute(
                "SELECT v.id, v.owner_id, v.background, v.voice_folder, v.music, "
                "       v.duration_s, v.qr_s, v.taken_at, "
                "       w.value AS views, w.measured_at "
                "FROM videos v JOIN views w ON w.video_id = v.id "
                "WHERE w.id = ("
                "  SELECT id FROM views x WHERE x.video_id = v.id "
                "  ORDER BY x.measured_at DESC, x.id DESC LIMIT 1"
                ")"))


def _video(row: sqlite3.Row) -> Video:
    return Video(
        id=row["id"], name=row["name"], file_id=row["file_id"],
        duration_s=row["duration_s"], background=row["background"],
        voice_folder=row["voice_folder"], music=bool(row["music"]),
        qr_s=row["qr_s"], owner_id=row["owner_id"], taken_at=row["taken_at"],
    )
