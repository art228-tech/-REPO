"""
Асинхронная база данных на SQLite.
Содержит схему, миграции и все операции с данными.
"""
from __future__ import annotations

import json
import secrets
import time
from typing import Any, Optional

import aiosqlite


SCHEMA = """
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;

-- Приветочные боты (привет-боты), которыми управляет конструктор
CREATE TABLE IF NOT EXISTS greeting_bots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    token           TEXT UNIQUE NOT NULL,
    tg_id           INTEGER UNIQUE NOT NULL,
    username        TEXT,
    name            TEXT,
    owner_id        INTEGER NOT NULL,
    join_delay      INTEGER DEFAULT 0,
    delete_timer    INTEGER DEFAULT 10,
    typing_mode         INTEGER DEFAULT 0,
    is_active       INTEGER DEFAULT 1,
    created_at      INTEGER NOT NULL
);

-- Шаги сценария (упорядоченные)
CREATE TABLE IF NOT EXISTS steps (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    bot_id              INTEGER NOT NULL,
    step_order          INTEGER NOT NULL,
    step_type           TEXT NOT NULL,                 -- 'roulette' | 'op' | 'message'
    config              TEXT NOT NULL,                 -- JSON конфиг
    duplicate_after     INTEGER DEFAULT 60,            -- через сколько секунд дублировать
    duplicate_increment INTEGER DEFAULT 0,             -- прибавлять с каждым разом
    duplicate_max       INTEGER DEFAULT 3,             -- макс. кол-во дублей
    FOREIGN KEY (bot_id) REFERENCES greeting_bots(id) ON DELETE CASCADE
);

-- Пользователи приветок
CREATE TABLE IF NOT EXISTS bot_users (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    bot_id              INTEGER NOT NULL,
    tg_id               INTEGER NOT NULL,
    username            TEXT,
    first_name          TEXT,
    is_premium          INTEGER DEFAULT 0,
    is_alive            INTEGER DEFAULT 1,             -- 0 если заблокировал
    ref_link_id         INTEGER,
    source              TEXT DEFAULT 'start',
    joined_channel      INTEGER DEFAULT 0,
    channel_link_id     INTEGER,
    current_step_order  INTEGER DEFAULT 0,             -- 0..n; -1 = сценарий начат, n+ = завершён
    completed           INTEGER DEFAULT 0,
    last_message_id     INTEGER,
    last_message_chat_id INTEGER,
    last_sent_at        INTEGER,
    duplicate_count     INTEGER DEFAULT 0,
    awaiting_user_msg   INTEGER DEFAULT 0,             -- ждём текст от юзера? (для message-этапа)
    awaiting_kb_text    TEXT,                          -- текст кнопки клавиатуры, если ждём
    created_at          INTEGER NOT NULL,
    UNIQUE (bot_id, tg_id),
    FOREIGN KEY (bot_id) REFERENCES greeting_bots(id) ON DELETE CASCADE,
    FOREIGN KEY (ref_link_id) REFERENCES ref_links(id) ON DELETE SET NULL
);

-- Реферальные ссылки
CREATE TABLE IF NOT EXISTS ref_links (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    bot_id      INTEGER NOT NULL,
    code        TEXT NOT NULL,
    name        TEXT,
    created_at  INTEGER NOT NULL,
    UNIQUE (bot_id, code),
    FOREIGN KEY (bot_id) REFERENCES greeting_bots(id) ON DELETE CASCADE
);

-- Прохождения шагов (для статистики)
CREATE TABLE IF NOT EXISTS step_completions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    step_id     INTEGER NOT NULL,
    completed_at INTEGER NOT NULL,
    FOREIGN KEY (user_id) REFERENCES bot_users(id) ON DELETE CASCADE,
    FOREIGN KEY (step_id) REFERENCES steps(id) ON DELETE CASCADE
);

-- Призы рулетки (для лога)
CREATE TABLE IF NOT EXISTS roulette_wins (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    step_id     INTEGER NOT NULL,
    amount      INTEGER NOT NULL,
    won_at      INTEGER NOT NULL,
    FOREIGN KEY (user_id) REFERENCES bot_users(id) ON DELETE CASCADE
);

-- Состояние админских FSM (мы храним свои данные, чтобы выживать рестарт)
CREATE TABLE IF NOT EXISTS admin_state (
    user_id     INTEGER PRIMARY KEY,
    state       TEXT,
    data        TEXT                                  -- JSON
);

-- Заявки на вступление в каналы (для проверки спонсоров типа «по заявкам»)
CREATE TABLE IF NOT EXISTS pending_join_requests (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    bot_id      INTEGER NOT NULL,
    channel_id  INTEGER NOT NULL,
    user_tg_id  INTEGER NOT NULL,
    created_at  INTEGER NOT NULL,
    UNIQUE(bot_id, channel_id, user_tg_id),
    FOREIGN KEY (bot_id) REFERENCES greeting_bots(id) ON DELETE CASCADE
);

-- Инвайт-ссылки канала (статистика вступлений)
CREATE TABLE IF NOT EXISTS channel_links (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    bot_id          INTEGER NOT NULL,
    channel_id      INTEGER NOT NULL,
    name            TEXT NOT NULL,
    invite_link     TEXT NOT NULL,
    joined_count    INTEGER NOT NULL DEFAULT 0,
    requested_count INTEGER NOT NULL DEFAULT 0,
    created_at      INTEGER NOT NULL,
    FOREIGN KEY (bot_id) REFERENCES greeting_bots(id) ON DELETE CASCADE
);

-- Отложенный старт сценария (переживает перезапуск бота)
CREATE TABLE IF NOT EXISTS scheduled_starts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    bot_id      INTEGER NOT NULL,
    user_id     INTEGER NOT NULL,
    fire_at     INTEGER NOT NULL,
    created_at  INTEGER NOT NULL,
    UNIQUE(bot_id, user_id),
    FOREIGN KEY (bot_id) REFERENCES greeting_bots(id) ON DELETE CASCADE
);

-- Индексы
CREATE INDEX IF NOT EXISTS idx_steps_bot_order ON steps(bot_id, step_order);
CREATE INDEX IF NOT EXISTS idx_users_bot ON bot_users(bot_id);
CREATE INDEX IF NOT EXISTS idx_users_step ON bot_users(bot_id, current_step_order);
CREATE INDEX IF NOT EXISTS idx_completions ON step_completions(step_id, user_id);
CREATE INDEX IF NOT EXISTS idx_sched ON scheduled_starts(fire_at);
CREATE INDEX IF NOT EXISTS idx_pjr ON pending_join_requests(bot_id, channel_id, user_tg_id);
CREATE INDEX IF NOT EXISTS idx_chlinks ON channel_links(bot_id, invite_link);
"""


def now() -> int:
    return int(time.time())


class DB:
    def __init__(self, path: str):
        self.path = path
        self._conn: Optional[aiosqlite.Connection] = None

    async def add_channel_link(self, bot_id, channel_id, name, invite_link):
        await self.conn.execute(
            "INSERT INTO channel_links(bot_id,channel_id,name,invite_link,created_at) "
            "VALUES (?,?,?,?,?)",
            (bot_id, int(channel_id), name, invite_link, now()),
        )
        await self.conn.commit()

    async def list_channel_links(self, bot_id):
        cur = await self.conn.execute(
            "SELECT * FROM channel_links WHERE bot_id=? ORDER BY id DESC", (bot_id,)
        )
        return await cur.fetchall()

    async def get_channel_link(self, link_id):
        cur = await self.conn.execute(
            "SELECT * FROM channel_links WHERE id=?", (link_id,)
        )
        return await cur.fetchone()

    async def get_channel_link_by_url(self, invite_link):
        cur = await self.conn.execute(
            "SELECT * FROM channel_links WHERE invite_link=?", (invite_link,)
        )
        return await cur.fetchone()

    async def delete_channel_link(self, link_id):
        await self.conn.execute("DELETE FROM channel_links WHERE id=?", (link_id,))
        await self.conn.commit()

    async def inc_channel_link(self, invite_link, *, joined=0, requested=0):
        await self.conn.execute(
            "UPDATE channel_links SET joined_count=joined_count+?, "
            "requested_count=requested_count+? WHERE invite_link=?",
            (joined, requested, invite_link),
        )
        await self.conn.commit()

    async def connect(self) -> None:
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript(SCHEMA)
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()

    @property
    def conn(self) -> aiosqlite.Connection:
        assert self._conn is not None, "DB not connected"
        return self._conn

    # ---------- Greeting bots ----------

    async def add_greeting_bot(
        self, token: str, tg_id: int, username: str, name: str, owner_id: int
    ) -> int:
        cur = await self.conn.execute(
            "INSERT INTO greeting_bots (token, tg_id, username, name, owner_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (token, tg_id, username, name, owner_id, now()),
        )
        await self.conn.commit()
        return cur.lastrowid  # type: ignore

    async def list_greeting_bots(self, owner_id: Optional[int] = None) -> list[aiosqlite.Row]:
        if owner_id is None:
            cur = await self.conn.execute(
                "SELECT * FROM greeting_bots ORDER BY id DESC"
            )
        else:
            cur = await self.conn.execute(
                "SELECT * FROM greeting_bots WHERE owner_id = ? ORDER BY id DESC",
                (owner_id,),
            )
        return await cur.fetchall()

    async def get_greeting_bot(self, bot_id: int) -> Optional[aiosqlite.Row]:
        cur = await self.conn.execute(
            "SELECT * FROM greeting_bots WHERE id = ?", (bot_id,)
        )
        return await cur.fetchone()

    async def get_greeting_bot_by_tg_id(self, tg_id: int) -> Optional[aiosqlite.Row]:
        cur = await self.conn.execute(
            "SELECT * FROM greeting_bots WHERE tg_id = ?", (tg_id,)
        )
        return await cur.fetchone()

    async def delete_greeting_bot(self, bot_id: int) -> None:
        await self.conn.execute("DELETE FROM greeting_bots WHERE id = ?", (bot_id,))
        await self.conn.commit()

    async def update_greeting_bot_settings(
        self, bot_id: int, *, join_delay: int | None = None, delete_timer: int | None = None,
        typing_mode: int | None = None
    ) -> None:
        sets, params = [], []
        if join_delay is not None:
            sets.append("join_delay = ?")
            params.append(join_delay)
        if typing_mode is not None:
            sets.append("typing_mode = ?")
            params.append(typing_mode)
        if delete_timer is not None:
            sets.append("delete_timer = ?")
            params.append(delete_timer)
        if not sets:
            return
        params.append(bot_id)
        await self.conn.execute(
            f"UPDATE greeting_bots SET {', '.join(sets)} WHERE id = ?", params
        )
        await self.conn.commit()

    # ---------- Steps ----------

    async def add_step(
        self,
        bot_id: int,
        step_type: str,
        config: dict,
        *,
        duplicate_after: int = 60,
        duplicate_increment: int = 0,
        duplicate_max: int = 3,
    ) -> int:
        cur = await self.conn.execute(
            "SELECT COALESCE(MAX(step_order), -1) + 1 FROM steps WHERE bot_id = ?",
            (bot_id,),
        )
        order = (await cur.fetchone())[0]
        cur = await self.conn.execute(
            "INSERT INTO steps "
            "(bot_id, step_order, step_type, config, duplicate_after, duplicate_increment, duplicate_max) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (bot_id, order, step_type, json.dumps(config, ensure_ascii=False),
             duplicate_after, duplicate_increment, duplicate_max),
        )
        await self.conn.commit()
        return cur.lastrowid  # type: ignore

    async def list_steps(self, bot_id: int) -> list[aiosqlite.Row]:
        cur = await self.conn.execute(
            "SELECT * FROM steps WHERE bot_id = ? ORDER BY step_order ASC",
            (bot_id,),
        )
        return await cur.fetchall()

    async def get_step(self, step_id: int) -> Optional[aiosqlite.Row]:
        cur = await self.conn.execute("SELECT * FROM steps WHERE id = ?", (step_id,))
        return await cur.fetchone()

    async def mark_copy_broken(self, step_id: int, broken: int = 1):
        """Помечает шаг как «оригинал копии удалён»."""
        await self.conn.execute(
            "UPDATE steps SET copy_broken=? WHERE id=?", (broken, step_id)
        )
        await self.conn.commit()

    async def add_welcome_channel(self, bot_id, chat_id, title):
        await self.conn.execute(
            "INSERT OR IGNORE INTO welcome_channels(bot_id,chat_id,title,start_delay,created_at) "
            "VALUES (?,?,?,0,?)", (bot_id, int(chat_id), title, now())
        )
        await self.conn.commit()

    async def list_welcome_channels(self, bot_id):
        cur = await self.conn.execute(
            "SELECT * FROM welcome_channels WHERE bot_id=? ORDER BY id", (bot_id,)
        )
        return await cur.fetchall()

    async def get_welcome_channel(self, wch_id):
        cur = await self.conn.execute("SELECT * FROM welcome_channels WHERE id=?", (wch_id,))
        return await cur.fetchone()

    async def get_welcome_channel_by_chat(self, bot_id, chat_id):
        cur = await self.conn.execute(
            "SELECT * FROM welcome_channels WHERE bot_id=? AND chat_id=?", (bot_id, int(chat_id))
        )
        return await cur.fetchone()

    async def set_welcome_channel_delay(self, wch_id, delay):
        await self.conn.execute(
            "UPDATE welcome_channels SET start_delay=? WHERE id=?", (int(delay), wch_id)
        )
        await self.conn.commit()

    async def delete_welcome_channel(self, wch_id):
        await self.conn.execute("DELETE FROM welcome_channels WHERE id=?", (wch_id,))
        await self.conn.commit()

    async def get_step_by_order(self, bot_id: int, order: int) -> Optional[aiosqlite.Row]:
        cur = await self.conn.execute(
            "SELECT * FROM steps WHERE bot_id = ? AND step_order = ?",
            (bot_id, order),
        )
        return await cur.fetchone()

    async def update_step(self, step_id: int, **fields) -> None:
        if "config" in fields and isinstance(fields["config"], dict):
            fields["config"] = json.dumps(fields["config"], ensure_ascii=False)
        sets = ", ".join(f"{k} = ?" for k in fields)
        params = list(fields.values()) + [step_id]
        await self.conn.execute(f"UPDATE steps SET {sets} WHERE id = ?", params)
        await self.conn.commit()

    async def delete_step(self, step_id: int) -> None:
        step = await self.get_step(step_id)
        if not step:
            return
        await self.conn.execute("DELETE FROM steps WHERE id = ?", (step_id,))
        # Сдвигаем порядок остальных шагов
        await self.conn.execute(
            "UPDATE steps SET step_order = step_order - 1 "
            "WHERE bot_id = ? AND step_order > ?",
            (step["bot_id"], step["step_order"]),
        )
        await self.conn.commit()

    async def move_step(self, step_id: int, direction: int) -> None:
        """direction: -1 — вверх, +1 — вниз."""
        step = await self.get_step(step_id)
        if not step:
            return
        new_order = step["step_order"] + direction
        other = await self.get_step_by_order(step["bot_id"], new_order)
        if not other:
            return
        await self.conn.execute(
            "UPDATE steps SET step_order = ? WHERE id = ?", (-1, step["id"])
        )
        await self.conn.execute(
            "UPDATE steps SET step_order = ? WHERE id = ?", (step["step_order"], other["id"])
        )
        await self.conn.execute(
            "UPDATE steps SET step_order = ? WHERE id = ?", (new_order, step["id"])
        )
        await self.conn.commit()

    # ---------- Users ----------

    async def set_user_channel_link(self, bot_id: int, tg_id: int, channel_link_id: int):
        """Помечает, по какой инвайт-ссылке канала пришёл юзер (если ещё не помечен)."""
        await self.conn.execute(
            "UPDATE bot_users SET channel_link_id=? "
            "WHERE bot_id=? AND tg_id=? AND channel_link_id IS NULL",
            (channel_link_id, bot_id, tg_id),
        )
        await self.conn.commit()

    async def schedule_start(self, bot_id: int, user_id: int, fire_at: int):
        """Планирует отложенный старт сценария (или обновляет время)."""
        await self.conn.execute(
            "INSERT INTO scheduled_starts(bot_id,user_id,fire_at,created_at) "
            "VALUES (?,?,?,?) ON CONFLICT(bot_id,user_id) DO UPDATE SET fire_at=excluded.fire_at",
            (bot_id, user_id, fire_at, now()),
        )
        await self.conn.commit()

    async def cancel_scheduled_start(self, bot_id: int, user_id: int):
        await self.conn.execute(
            "DELETE FROM scheduled_starts WHERE bot_id=? AND user_id=?",
            (bot_id, user_id),
        )
        await self.conn.commit()

    async def due_scheduled_starts(self, ts: int):
        """Возвращает старты, которым уже пора (fire_at <= ts)."""
        cur = await self.conn.execute(
            "SELECT * FROM scheduled_starts WHERE fire_at <= ? ORDER BY fire_at", (ts,)
        )
        return await cur.fetchall()

    async def upsert_user(
        self,
        bot_id: int,
        tg_id: int,
        *,
        username: str | None = None,
        first_name: str | None = None,
        is_premium: bool = False,
        ref_link_id: int | None = None,
        source: str = "start",
    ) -> aiosqlite.Row:
        cur = await self.conn.execute(
            "SELECT * FROM bot_users WHERE bot_id = ? AND tg_id = ?", (bot_id, tg_id)
        )
        existing = await cur.fetchone()
        if existing:
            await self.conn.execute(
                "UPDATE bot_users SET username = ?, first_name = ?, is_premium = ?, is_alive = 1 "
                "WHERE id = ?",
                (username, first_name, int(is_premium), existing["id"]),
            )
            await self.conn.commit()
            cur = await self.conn.execute(
                "SELECT * FROM bot_users WHERE id = ?", (existing["id"],)
            )
            return await cur.fetchone()  # type: ignore
        cur = await self.conn.execute(
            "INSERT INTO bot_users "
            "(bot_id, tg_id, username, first_name, is_premium, ref_link_id, source, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (bot_id, tg_id, username, first_name, int(is_premium), ref_link_id, source, now()),
        )
        await self.conn.commit()
        cur = await self.conn.execute(
            "SELECT * FROM bot_users WHERE id = ?", (cur.lastrowid,)
        )
        return await cur.fetchone()  # type: ignore

    async def mark_joined_channel(self, bot_id: int, tg_id: int):
        """Помечает, что юзер реально вступил в канал."""
        await self.conn.execute(
            "UPDATE bot_users SET joined_channel=1 WHERE bot_id=? AND tg_id=?",
            (bot_id, tg_id),
        )
        await self.conn.commit()

    async def get_user(self, user_id: int) -> Optional[aiosqlite.Row]:
        cur = await self.conn.execute("SELECT * FROM bot_users WHERE id = ?", (user_id,))
        return await cur.fetchone()

    async def get_user_by_tg(self, bot_id: int, tg_id: int) -> Optional[aiosqlite.Row]:
        cur = await self.conn.execute(
            "SELECT * FROM bot_users WHERE bot_id = ? AND tg_id = ?", (bot_id, tg_id)
        )
        return await cur.fetchone()

    async def list_users(self, bot_id: int) -> list[aiosqlite.Row]:
        cur = await self.conn.execute(
            "SELECT * FROM bot_users WHERE bot_id = ?", (bot_id,)
        )
        return await cur.fetchall()

    async def list_alive_user_tg_ids(self, bot_id: int) -> list[int]:
        cur = await self.conn.execute(
            "SELECT tg_id FROM bot_users WHERE bot_id = ? AND is_alive = 1", (bot_id,)
        )
        return [r[0] for r in await cur.fetchall()]

    async def update_user(self, user_id: int, **fields) -> None:
        if not fields:
            return
        sets = ", ".join(f"{k} = ?" for k in fields)
        params = list(fields.values()) + [user_id]
        await self.conn.execute(f"UPDATE bot_users SET {sets} WHERE id = ?", params)
        await self.conn.commit()

    async def mark_user_dead(self, user_id: int) -> None:
        await self.conn.execute(
            "UPDATE bot_users SET is_alive = 0 WHERE id = ?", (user_id,)
        )
        await self.conn.commit()

    async def reset_user_progress(self, user_id: int) -> None:
        await self.conn.execute(
            "UPDATE bot_users SET current_step_order = 0, completed = 0, "
            "duplicate_count = 0, last_message_id = NULL, last_message_chat_id = NULL, "
            "last_sent_at = NULL, awaiting_user_msg = 0, awaiting_kb_text = NULL "
            "WHERE id = ?",
            (user_id,),
        )
        await self.conn.commit()

    # ---------- Pending join requests (патч 4: спонсоры «по заявкам») ----------

    async def add_pending_join_request(self, bot_id: int, channel_id: int, user_tg_id: int) -> None:
        """Запоминает что юзер подал заявку в канал. Для спонсоров «по заявкам»."""
        await self.conn.execute(
            "INSERT OR IGNORE INTO pending_join_requests(bot_id, channel_id, user_tg_id, created_at) VALUES (?, ?, ?, ?)",
            (bot_id, int(channel_id), int(user_tg_id), now()),
        )
        await self.conn.commit()

    async def has_pending_join_request(self, bot_id: int, channel_id: int, user_tg_id: int) -> bool:
        cur = await self.conn.execute(
            "SELECT 1 FROM pending_join_requests WHERE bot_id=? AND channel_id=? AND user_tg_id=? LIMIT 1",
            (bot_id, int(channel_id), int(user_tg_id)),
        )
        return (await cur.fetchone()) is not None

    async def is_request_sponsor_channel(self, bot_id: int, channel_id: int) -> bool:
        """True, если у этой приветки есть шаг ОП со спонсором request_mode=True и таким channel_id."""
        import json as _json
        cur = await self.conn.execute(
            "SELECT config FROM steps WHERE bot_id=? AND step_type='op'",
            (bot_id,),
        )
        rows = await cur.fetchall()
        for r in rows:
            try:
                cfg = _json.loads(r[0])
            except Exception:
                continue
            for sp in cfg.get("sponsors", []):
                if sp.get("request_mode") and str(sp.get("channel_id")) == str(channel_id):
                    return True
        return False

    # ---------- Step completions ----------

    async def record_step_completion(self, user_id: int, step_id: int) -> None:
        await self.conn.execute(
            "INSERT INTO step_completions (user_id, step_id, completed_at) VALUES (?, ?, ?)",
            (user_id, step_id, now()),
        )
        await self.conn.commit()

    async def has_completed_step(self, user_id: int, step_id: int) -> bool:
        cur = await self.conn.execute(
            "SELECT 1 FROM step_completions WHERE user_id = ? AND step_id = ? LIMIT 1",
            (user_id, step_id),
        )
        return (await cur.fetchone()) is not None

    # ---------- Roulette ----------

    async def record_roulette_win(self, user_id: int, step_id: int, amount: int) -> None:
        await self.conn.execute(
            "INSERT INTO roulette_wins (user_id, step_id, amount, won_at) VALUES (?, ?, ?, ?)",
            (user_id, step_id, amount, now()),
        )
        await self.conn.commit()

    # ---------- Ref links ----------

    async def add_ref_link(self, bot_id: int, name: str) -> aiosqlite.Row:
        for _ in range(8):
            code = secrets.token_urlsafe(6).replace("-", "").replace("_", "")[:8]
            try:
                cur = await self.conn.execute(
                    "INSERT INTO ref_links (bot_id, code, name, created_at) VALUES (?, ?, ?, ?)",
                    (bot_id, code, name, now()),
                )
                await self.conn.commit()
                cur = await self.conn.execute(
                    "SELECT * FROM ref_links WHERE id = ?", (cur.lastrowid,)
                )
                return await cur.fetchone()  # type: ignore
            except aiosqlite.IntegrityError:
                continue
        raise RuntimeError("Не удалось сгенерировать уникальный код ссылки")

    async def list_ref_links(self, bot_id: int) -> list[aiosqlite.Row]:
        cur = await self.conn.execute(
            "SELECT * FROM ref_links WHERE bot_id = ? ORDER BY id DESC", (bot_id,)
        )
        return await cur.fetchall()

    async def get_ref_link_by_code(self, bot_id: int, code: str) -> Optional[aiosqlite.Row]:
        cur = await self.conn.execute(
            "SELECT * FROM ref_links WHERE bot_id = ? AND code = ?", (bot_id, code)
        )
        return await cur.fetchone()

    async def get_ref_link(self, ref_id: int) -> Optional[aiosqlite.Row]:
        cur = await self.conn.execute("SELECT * FROM ref_links WHERE id = ?", (ref_id,))
        return await cur.fetchone()

    async def delete_ref_link(self, ref_id: int) -> None:
        await self.conn.execute("DELETE FROM ref_links WHERE id = ?", (ref_id,))
        await self.conn.commit()

    # ---------- Admin FSM ----------

    async def set_admin_state(self, user_id: int, state: Optional[str], data: dict | None = None) -> None:
        if state is None:
            await self.conn.execute("DELETE FROM admin_state WHERE user_id = ?", (user_id,))
        else:
            await self.conn.execute(
                "INSERT INTO admin_state (user_id, state, data) VALUES (?, ?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET state = excluded.state, data = excluded.data",
                (user_id, state, json.dumps(data or {}, ensure_ascii=False)),
            )
        await self.conn.commit()

    async def get_admin_state(self, user_id: int) -> tuple[Optional[str], dict]:
        cur = await self.conn.execute(
            "SELECT state, data FROM admin_state WHERE user_id = ?", (user_id,)
        )
        row = await cur.fetchone()
        if not row:
            return None, {}
        return row["state"], json.loads(row["data"] or "{}")


_db_instance: Optional[DB] = None


def get_db() -> DB:
    assert _db_instance is not None, "DB не инициализирована"
    return _db_instance


async def init_db(path: str) -> DB:
    global _db_instance
    _db_instance = DB(path)
    await _db_instance.connect()
    return _db_instance
