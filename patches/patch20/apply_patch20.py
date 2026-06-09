#!/usr/bin/env python3
"""
Патч 20: персистентная задержка старта сценария.

Проблема: join_delay (отложенный старт, в т.ч. «через день») жил только
в оперативной памяти через asyncio-задачу. Любой перезапуск бота
(установка патча, падение, ребут сервера) — и задача теряется,
юзер не получает сценарий.

Решение: запланированный старт дублируется в таблицу scheduled_starts.
Фоновый воркер раз в 30 сек проверяет, кому пора, и запускает.
После отправки запись удаляется. Память тоже оставлена (для быстрого
старта), БД — надёжная подстраховка, переживающая перезапуск.
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


# === 1. БД: таблица scheduled_starts + методы ===
DB = ROOT / "database/db.py"
db_src = DB.read_text(encoding="utf-8")
if "scheduled_starts" not in db_src:
    db_src = db_src.replace(
        "-- Индексы\n",
        '''-- Отложенный старт сценария (переживает перезапуск бота)
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
''',
        1,
    )
    db_src = db_src.replace(
        "CREATE INDEX IF NOT EXISTS idx_completions ON step_completions(step_id, user_id);",
        "CREATE INDEX IF NOT EXISTS idx_completions ON step_completions(step_id, user_id);\n"
        "CREATE INDEX IF NOT EXISTS idx_sched ON scheduled_starts(fire_at);",
    )
    DB.write_text(db_src, encoding="utf-8")
    print("  ✓ database/db.py — таблица scheduled_starts")

# миграция существующей БД
dbp = str(ROOT / "data.db")
if Path(dbp).exists():
    conn = sqlite3.connect(dbp)
    conn.execute('''CREATE TABLE IF NOT EXISTS scheduled_starts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        bot_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        fire_at INTEGER NOT NULL,
        created_at INTEGER NOT NULL,
        UNIQUE(bot_id, user_id)
    )''')
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sched ON scheduled_starts(fire_at)")
    conn.commit()
    conn.close()
    print("  ✓ data.db — таблица scheduled_starts создана")

# методы доступа
db_src = DB.read_text(encoding="utf-8")
if "schedule_start" not in db_src:
    idx = db_src.find("    async def upsert_user(")
    methods = (
        "    async def schedule_start(self, bot_id: int, user_id: int, fire_at: int):\n"
        '        """Планирует отложенный старт сценария (или обновляет время)."""\n'
        "        await self.conn.execute(\n"
        '            "INSERT INTO scheduled_starts(bot_id,user_id,fire_at,created_at) "\n'
        '            "VALUES (?,?,?,?) ON CONFLICT(bot_id,user_id) DO UPDATE SET fire_at=excluded.fire_at",\n'
        "            (bot_id, user_id, fire_at, now()),\n"
        "        )\n"
        "        await self.conn.commit()\n"
        "\n"
        "    async def cancel_scheduled_start(self, bot_id: int, user_id: int):\n"
        "        await self.conn.execute(\n"
        '            "DELETE FROM scheduled_starts WHERE bot_id=? AND user_id=?",\n'
        "            (bot_id, user_id),\n"
        "        )\n"
        "        await self.conn.commit()\n"
        "\n"
        "    async def due_scheduled_starts(self, ts: int):\n"
        '        """Возвращает старты, которым уже пора (fire_at <= ts)."""\n'
        "        cur = await self.conn.execute(\n"
        '            "SELECT * FROM scheduled_starts WHERE fire_at <= ? ORDER BY fire_at", (ts,)\n'
        "        )\n"
        "        return await cur.fetchall()\n"
        "\n"
    )
    db_src = db_src[:idx] + methods + db_src[idx:]
    DB.write_text(db_src, encoding="utf-8")
    print("  ✓ database/db.py — методы schedule_start / cancel / due")

# === 2. scenario.py: пишем в БД при планировании, чистим при старте ===
SN = ROOT / "bots/scenario.py"

# 2a. в _schedule_delayed_start — дублируем в БД
patch(
    SN,
    '''    async def _schedule_delayed_start(
        self, bot: Bot, bot_record, user_id: int, delay: int
    ) -> None:
        key = (bot_record["id"], user_id)
        old = self._delay_tasks.pop(key, None)
        if old:
            old.cancel()
        task = asyncio.create_task(self._delayed_start_runner(bot, bot_record, user_id, delay))
        self._delay_tasks[key] = task''',
    '''    async def _schedule_delayed_start(
        self, bot: Bot, bot_record, user_id: int, delay: int
    ) -> None:
        key = (bot_record["id"], user_id)
        old = self._delay_tasks.pop(key, None)
        if old:
            old.cancel()
        # Дублируем в БД — переживёт перезапуск бота.
        import time as _t
        try:
            await get_db().schedule_start(
                bot_record["id"], user_id, int(_t.time()) + int(delay)
            )
        except Exception as _e:
            log.warning("schedule_start db: %s", _e)
        task = asyncio.create_task(self._delayed_start_runner(bot, bot_record, user_id, delay))
        self._delay_tasks[key] = task''',
    "запись отложенного старта в БД",
)

# 2b. в _delayed_start_runner — после отправки чистим запись из БД
patch(
    SN,
    '''    async def _delayed_start_runner(self, bot: Bot, bot_record, user_id: int, delay: int) -> None:
        try:
            await asyncio.sleep(delay)
            await self._send_step_to_user(bot, bot_record, user_id, step_order=0)
        except asyncio.CancelledError:
            pass''',
    '''    async def _delayed_start_runner(self, bot: Bot, bot_record, user_id: int, delay: int) -> None:
        try:
            await asyncio.sleep(delay)
            await self._send_step_to_user(bot, bot_record, user_id, step_order=0)
        except asyncio.CancelledError:
            return
        # Старт отработал — убираем запись из БД, чтобы воркер не продублировал.
        try:
            await get_db().cancel_scheduled_start(bot_record["id"], user_id)
        except Exception as _e:
            log.warning("cancel_scheduled_start: %s", _e)

    async def run_due_starts(self, bot, bot_record) -> None:
        """Запускает отложенные старты, которым пора (вызывается воркером
        и при старте бота — восстановление после перезапуска)."""
        import time as _t
        db = get_db()
        try:
            due = await db.due_scheduled_starts(int(_t.time()))
        except Exception as e:
            log.warning("due_scheduled_starts: %s", e)
            return
        for row in due:
            if row["bot_id"] != bot_record["id"]:
                continue
            uid = row["user_id"]
            # снимаем запись ДО отправки — чтобы не задвоить
            try:
                await db.cancel_scheduled_start(bot_record["id"], uid)
            except Exception:
                pass
            # если в памяти ещё висит живая задача — не дублируем
            key = (bot_record["id"], uid)
            mem = self._delay_tasks.get(key)
            if mem and not mem.done():
                continue
            try:
                await self._send_step_to_user(bot, bot_record, uid, step_order=0)
                log.info("[bot %s] восстановлен отложенный старт user=%s",
                         bot_record["id"], uid)
            except Exception as e:
                log.warning("run_due_starts send: %s", e)''',
    "очистка БД + метод run_due_starts",
)

# === 3. greeter.py: фоновый воркер, проверяющий отложенные старты ===
GR = ROOT / "bots/greeter.py"
gr_src = GR.read_text(encoding="utf-8")
if "run_due_starts" not in gr_src:
    # Найдём register_greeter_handlers и добавим запуск воркера.
    # Воркер стартуем когда приветка запускается — добавим в конец функции
    # register_greeter_handlers через создание задачи.
    anchor = "    @dp.chat_join_request()"
    worker = '''    async def _due_starts_worker() -> None:
        """Каждые 30 сек проверяет отложенные старты — восстановление
        после перезапуска бота."""
        engine = get_engine()
        while True:
            try:
                await asyncio.sleep(30)
                bot_record = await _get_bot_record()
                if bot_record:
                    await engine.run_due_starts(bot, bot_record)
            except asyncio.CancelledError:
                return
            except Exception as e:
                log.warning("due_starts_worker: %s", e)

    asyncio.create_task(_due_starts_worker())

'''
    gr_src = gr_src.replace(anchor, worker + anchor, 1)
    # проверим что asyncio импортирован
    if "import asyncio" not in gr_src:
        gr_src = gr_src.replace("import logging", "import asyncio\nimport logging", 1)
    GR.write_text(gr_src, encoding="utf-8")
    print("  ✓ bots/greeter.py — фоновый воркер отложенных стартов")

print("\\n✅ Патч 20 применён. Перезапусти бот.")
