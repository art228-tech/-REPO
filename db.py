from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import aiosqlite

import config
from logger_setup import log


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    phone TEXT NOT NULL UNIQUE,
    session_name TEXT NOT NULL,
    proxy_json TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    last_error TEXT,
    spamblocked_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS contacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    identifier TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'pending',
    sent_by_account_id INTEGER,
    sent_at TEXT,
    error TEXT,
    msg1_text TEXT,
    msg2_text TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS message_variants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slot INTEGER NOT NULL,
    text TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS mailing_runs (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    status TEXT NOT NULL DEFAULT 'idle',
    chat_id INTEGER,
    stats_message_id INTEGER,
    started_at TEXT,
    stopped_at TEXT,
    last_error TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pending_auth (
    user_id INTEGER PRIMARY KEY,
    phone TEXT,
    phone_code_hash TEXT,
    proxy_json TEXT,
    step TEXT,
    created_at TEXT NOT NULL
);
"""


DEFAULT_SETTINGS = {
    "api_id": "",
    "api_hash": "",
    "delay_between_messages": "3-8",
    "delay_per_account": "45-90",
    "owner_ids": "",
}


def parse_delay_range(raw: str, default: tuple[int, int] = (1, 1)) -> tuple[int, int]:
    """
    Accepts: "30-60", "30 - 60", "45", "45s"
    Returns inclusive (min, max) with min<=max, min>=0, max>=1 for account delays.
    """
    text = (raw or "").strip().lower().replace("с", "").replace("s", "").strip()
    if not text:
        return default
    text = text.replace("—", "-").replace("–", "-")
    if "-" in text:
        left, right = text.split("-", 1)
        a = int(left.strip())
        b = int(right.strip())
    else:
        a = b = int(text)
    if a < 0 or b < 0:
        raise ValueError("Интервал не может быть отрицательным")
    lo, hi = (a, b) if a <= b else (b, a)
    return lo, hi


def format_delay_range(lo: int, hi: int) -> str:
    return f"{lo}-{hi}" if lo != hi else str(lo)


class Database:
    def __init__(self, path: str | None = None) -> None:
        self.path = str(path or config.DB_PATH)
        self._db: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self._db = await aiosqlite.connect(self.path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL;")
        await self._db.execute("PRAGMA foreign_keys=ON;")
        await self._db.executescript(SCHEMA)
        for key, value in DEFAULT_SETTINGS.items():
            await self._db.execute(
                "INSERT OR IGNORE INTO settings(key, value) VALUES(?, ?)",
                (key, value),
            )
        await self._db.execute(
            """
            INSERT OR IGNORE INTO mailing_runs(id, status, updated_at)
            VALUES(1, 'idle', ?)
            """,
            (utcnow(),),
        )
        # Seed API from env if DB empty
        if config.API_ID and not await self.get_setting("api_id"):
            await self.set_setting("api_id", str(config.API_ID))
        if config.API_HASH and not await self.get_setting("api_hash"):
            await self.set_setting("api_hash", config.API_HASH)
        await self._db.commit()
        log.info("Database ready at %s", self.path)

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    @property
    def db(self) -> aiosqlite.Connection:
        if not self._db:
            raise RuntimeError("Database is not connected")
        return self._db

    async def get_setting(self, key: str, default: str = "") -> str:
        async with self.db.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ) as cur:
            row = await cur.fetchone()
            return row["value"] if row else default

    async def set_setting(self, key: str, value: str) -> None:
        await self.db.execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        await self.db.commit()

    async def get_api_credentials(self) -> tuple[int, str]:
        api_id_raw = await self.get_setting("api_id") or str(config.API_ID or 0)
        api_hash = await self.get_setting("api_hash") or config.API_HASH
        try:
            api_id = int(api_id_raw)
        except ValueError:
            api_id = 0
        return api_id, api_hash

    async def get_delay_ranges(self) -> tuple[tuple[int, int], tuple[int, int]]:
        between = parse_delay_range(
            await self.get_setting("delay_between_messages", "3-8"), default=(3, 8)
        )
        per_acc = parse_delay_range(
            await self.get_setting("delay_per_account", "45-90"), default=(45, 90)
        )
        return between, per_acc

    async def pick_delays(self) -> tuple[int, int]:
        """Random seconds within configured ranges for this send cycle."""
        import random

        between_r, per_acc_r = await self.get_delay_ranges()
        between = random.randint(between_r[0], between_r[1])
        per_acc = random.randint(per_acc_r[0], per_acc_r[1])
        return between, per_acc

    # kept for compatibility
    async def get_delays(self) -> tuple[int, int]:
        return await self.pick_delays()

    # ---- owners ----
    async def get_owner_ids(self) -> list[int]:
        raw = await self.get_setting("owner_ids", "")
        if not raw.strip():
            return []
        result: list[int] = []
        for part in raw.split(","):
            part = part.strip()
            if part.isdigit():
                result.append(int(part))
        return result

    async def add_owner(self, user_id: int) -> None:
        owners = await self.get_owner_ids()
        if user_id not in owners:
            owners.append(user_id)
            await self.set_setting("owner_ids", ",".join(map(str, owners)))

    # ---- accounts ----
    async def add_account(
        self,
        phone: str,
        session_name: str,
        proxy_json: str | None = None,
        status: str = "active",
    ) -> int:
        now = utcnow()
        cur = await self.db.execute(
            """
            INSERT INTO accounts(phone, session_name, proxy_json, status, created_at, updated_at)
            VALUES(?, ?, ?, ?, ?, ?)
            ON CONFLICT(phone) DO UPDATE SET
                session_name = excluded.session_name,
                proxy_json = COALESCE(excluded.proxy_json, accounts.proxy_json),
                status = excluded.status,
                last_error = NULL,
                spamblocked_at = NULL,
                updated_at = excluded.updated_at
            """,
            (phone, session_name, proxy_json, status, now, now),
        )
        await self.db.commit()
        if cur.lastrowid:
            return int(cur.lastrowid)
        async with self.db.execute(
            "SELECT id FROM accounts WHERE phone = ?", (phone,)
        ) as c:
            row = await c.fetchone()
            return int(row["id"])

    async def list_accounts(self) -> list[aiosqlite.Row]:
        async with self.db.execute(
            "SELECT * FROM accounts ORDER BY id"
        ) as cur:
            return await cur.fetchall()

    async def get_account(self, account_id: int) -> aiosqlite.Row | None:
        async with self.db.execute(
            "SELECT * FROM accounts WHERE id = ?", (account_id,)
        ) as cur:
            return await cur.fetchone()

    async def get_account_by_phone(self, phone: str) -> aiosqlite.Row | None:
        async with self.db.execute(
            "SELECT * FROM accounts WHERE phone = ?", (phone,)
        ) as cur:
            return await cur.fetchone()

    async def update_account(
        self,
        account_id: int,
        *,
        status: str | None = None,
        last_error: str | None = None,
        proxy_json: str | None = None,
        clear_spamblock: bool = False,
        set_spamblock: bool = False,
    ) -> None:
        fields: list[str] = ["updated_at = ?"]
        values: list[Any] = [utcnow()]
        if status is not None:
            fields.append("status = ?")
            values.append(status)
        if last_error is not None:
            fields.append("last_error = ?")
            values.append(last_error)
        if proxy_json is not None:
            fields.append("proxy_json = ?")
            values.append(proxy_json if proxy_json != "" else None)
        if clear_spamblock:
            fields.append("spamblocked_at = NULL")
            if status is None:
                fields.append("status = ?")
                values.append("active")
        if set_spamblock:
            fields.append("spamblocked_at = ?")
            values.append(utcnow())
            if status is None:
                fields.append("status = ?")
                values.append("spamblock")
        values.append(account_id)
        await self.db.execute(
            f"UPDATE accounts SET {', '.join(fields)} WHERE id = ?",
            values,
        )
        await self.db.commit()

    async def delete_account(self, account_id: int) -> None:
        await self.db.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
        await self.db.commit()

    async def active_accounts(self) -> list[aiosqlite.Row]:
        async with self.db.execute(
            "SELECT * FROM accounts WHERE status = 'active' ORDER BY id"
        ) as cur:
            return await cur.fetchall()

    # ---- contacts ----
    async def import_contacts(self, identifiers: list[str], replace: bool = False) -> dict[str, int]:
        if replace:
            await self.db.execute("DELETE FROM contacts")
        added = 0
        skipped = 0
        now = utcnow()
        for ident in identifiers:
            try:
                cur = await self.db.execute(
                    """
                    INSERT INTO contacts(identifier, status, created_at, updated_at)
                    VALUES(?, 'pending', ?, ?)
                    """,
                    (ident, now, now),
                )
                if cur.rowcount:
                    added += 1
            except Exception:
                skipped += 1
        await self.db.commit()
        return {"added": added, "skipped": skipped, "total": await self.count_contacts()}

    async def count_contacts(self, status: str | None = None) -> int:
        if status:
            async with self.db.execute(
                "SELECT COUNT(*) AS c FROM contacts WHERE status = ?", (status,)
            ) as cur:
                row = await cur.fetchone()
                return int(row["c"])
        async with self.db.execute("SELECT COUNT(*) AS c FROM contacts") as cur:
            row = await cur.fetchone()
            return int(row["c"])

    async def contact_stats(self) -> dict[str, int]:
        async with self.db.execute(
            "SELECT status, COUNT(*) AS c FROM contacts GROUP BY status"
        ) as cur:
            rows = await cur.fetchall()
        stats = {"pending": 0, "sent": 0, "failed": 0, "skipped": 0, "total": 0}
        for row in rows:
            stats[row["status"]] = int(row["c"])
            stats["total"] += int(row["c"])
        return stats

    async def claim_pending_contact(self, account_id: int) -> aiosqlite.Row | None:
        """Atomically pick one pending contact (no duplicates across accounts)."""
        await self.db.execute("BEGIN IMMEDIATE")
        try:
            async with self.db.execute(
                """
                SELECT * FROM contacts
                WHERE status = 'pending'
                ORDER BY id
                LIMIT 1
                """
            ) as cur:
                row = await cur.fetchone()
            if not row:
                await self.db.commit()
                return None
            cur = await self.db.execute(
                """
                UPDATE contacts
                SET status = 'processing',
                    sent_by_account_id = ?,
                    updated_at = ?
                WHERE id = ? AND status = 'pending'
                """,
                (account_id, utcnow(), row["id"]),
            )
            await self.db.commit()
            if not cur.rowcount:
                return None
            async with self.db.execute(
                "SELECT * FROM contacts WHERE id = ?", (row["id"],)
            ) as cur2:
                return await cur2.fetchone()
        except Exception:
            await self.db.rollback()
            raise

    async def mark_contact_sent(
        self,
        contact_id: int,
        account_id: int,
        msg1: str,
        msg2: str | None,
    ) -> None:
        await self.db.execute(
            """
            UPDATE contacts
            SET status = 'sent',
                sent_by_account_id = ?,
                sent_at = ?,
                msg1_text = ?,
                msg2_text = ?,
                error = NULL,
                updated_at = ?
            WHERE id = ?
            """,
            (account_id, utcnow(), msg1, msg2, utcnow(), contact_id),
        )
        await self.db.commit()

    async def mark_contact_failed(self, contact_id: int, error: str) -> None:
        await self.db.execute(
            """
            UPDATE contacts
            SET status = 'failed', error = ?, updated_at = ?
            WHERE id = ?
            """,
            (error, utcnow(), contact_id),
        )
        await self.db.commit()

    async def requeue_contact(self, contact_id: int) -> None:
        await self.db.execute(
            """
            UPDATE contacts
            SET status = 'pending',
                sent_by_account_id = NULL,
                error = NULL,
                updated_at = ?
            WHERE id = ? AND status IN ('processing', 'failed')
            """,
            (utcnow(), contact_id),
        )
        await self.db.commit()

    async def requeue_processing(self) -> int:
        cur = await self.db.execute(
            """
            UPDATE contacts
            SET status = 'pending', sent_by_account_id = NULL, updated_at = ?
            WHERE status = 'processing'
            """,
            (utcnow(),),
        )
        await self.db.commit()
        return cur.rowcount or 0

    async def export_contacts(self, status: str) -> list[str]:
        async with self.db.execute(
            "SELECT identifier FROM contacts WHERE status = ? ORDER BY id",
            (status,),
        ) as cur:
            rows = await cur.fetchall()
        return [r["identifier"] for r in rows]

    async def clear_contacts(self) -> None:
        await self.db.execute("DELETE FROM contacts")
        await self.db.commit()

    # ---- messages ----
    async def add_variant(self, slot: int, text: str) -> int:
        cur = await self.db.execute(
            "INSERT INTO message_variants(slot, text, created_at) VALUES(?, ?, ?)",
            (slot, text, utcnow()),
        )
        await self.db.commit()
        return int(cur.lastrowid or 0)

    async def list_variants(self, slot: int | None = None) -> list[aiosqlite.Row]:
        if slot is None:
            async with self.db.execute(
                "SELECT * FROM message_variants ORDER BY slot, id"
            ) as cur:
                return await cur.fetchall()
        async with self.db.execute(
            "SELECT * FROM message_variants WHERE slot = ? ORDER BY id",
            (slot,),
        ) as cur:
            return await cur.fetchall()

    async def delete_variant(self, variant_id: int) -> None:
        await self.db.execute(
            "DELETE FROM message_variants WHERE id = ?", (variant_id,)
        )
        await self.db.commit()

    async def clear_variants(self, slot: int) -> None:
        await self.db.execute(
            "DELETE FROM message_variants WHERE slot = ?", (slot,)
        )
        await self.db.commit()

    # ---- mailing run ----
    async def get_run(self) -> aiosqlite.Row:
        async with self.db.execute("SELECT * FROM mailing_runs WHERE id = 1") as cur:
            row = await cur.fetchone()
            assert row is not None
            return row

    async def set_run(
        self,
        *,
        status: str | None = None,
        chat_id: int | None = None,
        stats_message_id: int | None = None,
        last_error: str | None = None,
        started: bool = False,
        stopped: bool = False,
        clear_error: bool = False,
    ) -> None:
        fields = ["updated_at = ?"]
        values: list[Any] = [utcnow()]
        if status is not None:
            fields.append("status = ?")
            values.append(status)
        if chat_id is not None:
            fields.append("chat_id = ?")
            values.append(chat_id)
        if stats_message_id is not None:
            fields.append("stats_message_id = ?")
            values.append(stats_message_id)
        if last_error is not None:
            fields.append("last_error = ?")
            values.append(last_error)
        if clear_error:
            fields.append("last_error = NULL")
        if started:
            fields.append("started_at = ?")
            values.append(utcnow())
            fields.append("stopped_at = NULL")
        if stopped:
            fields.append("stopped_at = ?")
            values.append(utcnow())
        await self.db.execute(
            f"UPDATE mailing_runs SET {', '.join(fields)} WHERE id = 1",
            values,
        )
        await self.db.commit()

    # ---- pending auth ----
    async def set_pending_auth(
        self,
        user_id: int,
        *,
        phone: str | None = None,
        phone_code_hash: str | None = None,
        proxy_json: str | None = None,
        step: str | None = None,
    ) -> None:
        now = utcnow()
        await self.db.execute(
            """
            INSERT INTO pending_auth(user_id, phone, phone_code_hash, proxy_json, step, created_at)
            VALUES(?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                phone = COALESCE(excluded.phone, pending_auth.phone),
                phone_code_hash = COALESCE(excluded.phone_code_hash, pending_auth.phone_code_hash),
                proxy_json = COALESCE(excluded.proxy_json, pending_auth.proxy_json),
                step = COALESCE(excluded.step, pending_auth.step)
            """,
            (user_id, phone, phone_code_hash, proxy_json, step, now),
        )
        await self.db.commit()

    async def get_pending_auth(self, user_id: int) -> aiosqlite.Row | None:
        async with self.db.execute(
            "SELECT * FROM pending_auth WHERE user_id = ?", (user_id,)
        ) as cur:
            return await cur.fetchone()

    async def clear_pending_auth(self, user_id: int) -> None:
        await self.db.execute("DELETE FROM pending_auth WHERE user_id = ?", (user_id,))
        await self.db.commit()


db = Database()


@dataclass
class ProxyConfig:
    proxy_type: str
    host: str
    port: int
    username: str | None = None
    password: str | None = None

    def to_json(self) -> str:
        return json.dumps(
            {
                "proxy_type": self.proxy_type,
                "host": self.host,
                "port": self.port,
                "username": self.username,
                "password": self.password,
            },
            ensure_ascii=False,
        )

    def to_telethon(self) -> tuple:
        # Telethon: (type, host, port, rdns, username, password)
        import socks

        ptype = self.proxy_type.lower()
        if ptype in ("socks5", "socks"):
            kind = socks.SOCKS5
        elif ptype == "socks4":
            kind = socks.SOCKS4
        elif ptype in ("http", "https"):
            kind = socks.HTTP
        else:
            raise ValueError(f"Unsupported proxy type: {self.proxy_type}")
        return (kind, self.host, self.port, True, self.username, self.password)

    @classmethod
    def parse(cls, raw: str) -> "ProxyConfig":
        """
        Supported:
          socks5://user:pass@host:port
          http://host:port
          socks5:host:port:user:pass
          host:port
        """
        text = raw.strip()
        if "://" in text:
            from urllib.parse import urlparse

            u = urlparse(text)
            if not u.hostname or not u.port:
                raise ValueError("Proxy must include host and port")
            return cls(
                proxy_type=u.scheme or "socks5",
                host=u.hostname,
                port=int(u.port),
                username=u.username,
                password=u.password,
            )
        parts = text.split(":")
        if len(parts) == 2:
            return cls("socks5", parts[0], int(parts[1]))
        if len(parts) == 4 and parts[0].lower() in (
            "socks5",
            "socks4",
            "http",
            "https",
            "socks",
        ):
            return cls(parts[0], parts[1], int(parts[2]), parts[3], None)
        if len(parts) == 5 and parts[0].lower() in (
            "socks5",
            "socks4",
            "http",
            "https",
            "socks",
        ):
            return cls(parts[0], parts[1], int(parts[2]), parts[3], parts[4])
        if len(parts) == 4:
            # host:port:user:pass
            return cls("socks5", parts[0], int(parts[1]), parts[2], parts[3])
        raise ValueError(
            "Формат прокси: socks5://user:pass@host:port или host:port:user:pass"
        )