#!/usr/bin/env python3
"""
Патч 27: привязка приветки к каналам + задержка старта для каждого канала.

- Таблица welcome_channels(bot_id, chat_id, title, start_delay).
- В настройках приветки — раздел «📢 Каналы приветки»: добавить канал
  по chat_id, задать задержку каналу, удалить.
- on_join_request: если канал заявки НЕ в списке приветки — игнор
  (приветка молчит). Пустой список = приветка не отвечает никому.
- Задержка старта берётся у конкретного канала.
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


DB = ROOT / "database/db.py"
GR = ROOT / "bots/greeter.py"
SN = ROOT / "bots/scenario.py"
KB = ROOT / "keyboards/constructor_kb.py"
FSM = ROOT / "states/fsm.py"
BM = ROOT / "handlers/bot_menu.py"

# === 1. Таблица welcome_channels + методы ===
dbp = str(ROOT / "data.db")
if Path(dbp).exists():
    conn = sqlite3.connect(dbp)
    conn.execute('''CREATE TABLE IF NOT EXISTS welcome_channels (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        bot_id INTEGER NOT NULL,
        chat_id INTEGER NOT NULL,
        title TEXT,
        start_delay INTEGER NOT NULL DEFAULT 0,
        created_at INTEGER NOT NULL,
        UNIQUE(bot_id, chat_id)
    )''')
    conn.execute("CREATE INDEX IF NOT EXISTS idx_wch ON welcome_channels(bot_id,chat_id)")
    conn.commit()
    conn.close()
    print("  ✓ data.db — таблица welcome_channels")

db_src = DB.read_text(encoding="utf-8")
if "welcome_channels" not in db_src:
    idx = db_src.find("    async def get_step_by_order(")
    methods = (
        "    async def add_welcome_channel(self, bot_id, chat_id, title):\n"
        "        await self.conn.execute(\n"
        '            "INSERT OR IGNORE INTO welcome_channels(bot_id,chat_id,title,start_delay,created_at) "\n'
        '            "VALUES (?,?,?,0,?)", (bot_id, int(chat_id), title, now())\n'
        "        )\n"
        "        await self.conn.commit()\n\n"
        "    async def list_welcome_channels(self, bot_id):\n"
        '        cur = await self.conn.execute(\n'
        '            "SELECT * FROM welcome_channels WHERE bot_id=? ORDER BY id", (bot_id,)\n'
        "        )\n"
        "        return await cur.fetchall()\n\n"
        "    async def get_welcome_channel(self, wch_id):\n"
        '        cur = await self.conn.execute("SELECT * FROM welcome_channels WHERE id=?", (wch_id,))\n'
        "        return await cur.fetchone()\n\n"
        "    async def get_welcome_channel_by_chat(self, bot_id, chat_id):\n"
        "        cur = await self.conn.execute(\n"
        '            "SELECT * FROM welcome_channels WHERE bot_id=? AND chat_id=?", (bot_id, int(chat_id))\n'
        "        )\n"
        "        return await cur.fetchone()\n\n"
        "    async def set_welcome_channel_delay(self, wch_id, delay):\n"
        '        await self.conn.execute(\n'
        '            "UPDATE welcome_channels SET start_delay=? WHERE id=?", (int(delay), wch_id)\n'
        "        )\n"
        "        await self.conn.commit()\n\n"
        "    async def delete_welcome_channel(self, wch_id):\n"
        '        await self.conn.execute("DELETE FROM welcome_channels WHERE id=?", (wch_id,))\n'
        "        await self.conn.commit()\n\n"
    )
    db_src = db_src[:idx] + methods + db_src[idx:]
    DB.write_text(db_src, encoding="utf-8")
    print("  ✓ database/db.py — методы welcome_channels")

# === 2. on_join_request: проверка канала ===
patch(
    GR,
    '''        user = await db.upsert_user(
            bot_record["id"],
            req.from_user.id,
            username=req.from_user.username,
            first_name=req.from_user.first_name,
            is_premium=bool(getattr(req.from_user, "is_premium", False)),
            source="request",
        )''',
    '''        # Приветка работает только с каналами из её списка.
        # Канал не в списке (или список пуст) — игнорируем заявку.
        _wch = await db.get_welcome_channel_by_chat(bot_record["id"], req.chat.id)
        if _wch is None:
            log.info(
                "[bot %s] заявка из канала %s — не в списке приветки, игнор",
                bot_record["id"], req.chat.id,
            )
            return
        user = await db.upsert_user(
            bot_record["id"],
            req.from_user.id,
            username=req.from_user.username,
            first_name=req.from_user.first_name,
            is_premium=bool(getattr(req.from_user, "is_premium", False)),
            source="request",
        )''',
    "проверка канала в on_join_request",
)

# передаём задержку канала в start_or_restart
patch(
    GR,
    '''        engine = get_engine()
        try:
            await engine.start_or_restart(req.bot, bot_record, user)''',
    '''        engine = get_engine()
        try:
            await engine.start_or_restart(
                req.bot, bot_record, user, delay_override=_wch["start_delay"]
            )''',
    "передача задержки канала",
)

# === 3. scenario: start_or_restart принимает delay_override ===
patch(
    SN,
    '''    async def start_or_restart(self, bot: Bot, bot_record, user) -> None:
        """Запускает сценарий с самого начала (или перезапускает, если уже идёт)."""
        db = get_db()
        # Отменяем все активные задачи
        self._cancel_all_for(bot_record["id"], user["id"])
        # Сбрасываем прогресс
        await db.reset_user_progress(user["id"])
        # Учитываем join_delay
        if bot_record["join_delay"] and bot_record["join_delay"] > 0:
            await self._schedule_delayed_start(
                bot, bot_record, user["id"], bot_record["join_delay"]
            )
        else:
            await self._send_step_to_user(bot, bot_record, user["id"], step_order=0)''',
    '''    async def start_or_restart(self, bot: Bot, bot_record, user,
                               delay_override=None) -> None:
        """Запускает сценарий с начала. delay_override — задержка канала
        (если задана, используется вместо общей join_delay)."""
        db = get_db()
        # Отменяем все активные задачи
        self._cancel_all_for(bot_record["id"], user["id"])
        # Сбрасываем прогресс
        await db.reset_user_progress(user["id"])
        # Задержка: канала (delay_override) либо общая join_delay
        if delay_override is not None:
            delay = int(delay_override)
        else:
            delay = int(bot_record["join_delay"] or 0)
        if delay > 0:
            await self._schedule_delayed_start(
                bot, bot_record, user["id"], delay
            )
        else:
            await self._send_step_to_user(bot, bot_record, user["id"], step_order=0)''',
    "start_or_restart с delay_override",
)

# === 4. FSM-стейты ===
fsm_src = FSM.read_text(encoding="utf-8")
if "wch_add_id" not in fsm_src:
    # добавляем в группу BotSettingsStates
    fsm_src = fsm_src.replace(
        "class BotSettingsStates(StatesGroup):",
        "class BotSettingsStates(StatesGroup):\n"
        "    wch_add_id = State()\n"
        "    wch_set_delay = State()",
        1,
    )
    FSM.write_text(fsm_src, encoding="utf-8")
    print("  ✓ states/fsm.py — стейты welcome-каналов")

# === 5. кнопка в settings_menu ===
patch(
    KB,
    '''        [InlineKeyboardButton(
            text=f"Вид приветки: {_tm}",
            callback_data=f"set_tm:{bot_id}",
        )],
        [InlineKeyboardButton(text="« Назад", callback_data=f"bot:{bot_id}")],''',
    '''        [InlineKeyboardButton(
            text=f"Вид приветки: {_tm}",
            callback_data=f"set_tm:{bot_id}",
        )],
        [InlineKeyboardButton(
            text="📢 Каналы приветки",
            callback_data=f"wch:{bot_id}",
        )],
        [InlineKeyboardButton(text="« Назад", callback_data=f"bot:{bot_id}")],''',
    "кнопка «Каналы приветки»",
)

# === 6. хендлеры welcome-каналов — отдельный файл ===
WCH = ROOT / "handlers/welcome_channels.py"
WCH.write_text('''"""Каналы приветки: список разрешённых каналов + задержка у каждого."""
from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message,
)

from database import get_db
from handlers.start import is_admin
from states.fsm import BotSettingsStates

router = Router()


def _menu(bot_id: int, channels: list) -> InlineKeyboardMarkup:
    rows = []
    for ch in channels:
        rows.append([InlineKeyboardButton(
            text=f"\\U0001F4E2 {ch['title'] or ch['chat_id']} \\u2014 {ch['start_delay']} \\u0441",
            callback_data=f"wchv:{ch['id']}")])
    rows.append([InlineKeyboardButton(text="\\u2795 \\u0414\\u043e\\u0431\\u0430\\u0432\\u0438\\u0442\\u044c \\u043a\\u0430\\u043d\\u0430\\u043b", callback_data=f"wch_add:{bot_id}")])
    rows.append([InlineKeyboardButton(text="\\u00ab \\u041d\\u0430\\u0437\\u0430\\u0434", callback_data=f"set:{bot_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data.startswith("wch:"))
async def cb_wch_list(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        await cb.answer("\\u26d4", show_alert=True)
        return
    await state.clear()
    bot_id = int(cb.data.split(":")[1])
    chs = await get_db().list_welcome_channels(bot_id)
    await cb.message.edit_text(
        "<b>\\U0001F4E2 \\u041a\\u0430\\u043d\\u0430\\u043b\\u044b \\u043f\\u0440\\u0438\\u0432\\u0435\\u0442\\u043a\\u0438</b>\\n\\n"
        f"\\u0412\\u0441\\u0435\\u0433\\u043e: {len(chs)}\\n\\n"
        "\\u041f\\u0440\\u0438\\u0432\\u0435\\u0442\\u043a\\u0430 \\u043e\\u0442\\u0432\\u0435\\u0447\\u0430\\u0435\\u0442 \\u0442\\u043e\\u043b\\u044c\\u043a\\u043e \\u043d\\u0430 \\u0437\\u0430\\u044f\\u0432\\u043a\\u0438 \\u0438\\u0437 \\u044d\\u0442\\u0438\\u0445 \\u043a\\u0430\\u043d\\u0430\\u043b\\u043e\\u0432. "
        "\\u0423 \\u043a\\u0430\\u0436\\u0434\\u043e\\u0433\\u043e \\u2014 \\u0441\\u0432\\u043e\\u044f \\u0437\\u0430\\u0434\\u0435\\u0440\\u0436\\u043a\\u0430 \\u0441\\u0442\\u0430\\u0440\\u0442\\u0430 \\u0441\\u0446\\u0435\\u043d\\u0430\\u0440\\u0438\\u044f.\\n"
        "<i>\\u0415\\u0441\\u043b\\u0438 \\u0441\\u043f\\u0438\\u0441\\u043e\\u043a \\u043f\\u0443\\u0441\\u0442 \\u2014 \\u043f\\u0440\\u0438\\u0432\\u0435\\u0442\\u043a\\u0430 \\u043d\\u0435 \\u043f\\u0438\\u0448\\u0435\\u0442 \\u043d\\u0438\\u043a\\u043e\\u043c\\u0443.</i>",
        reply_markup=_menu(bot_id, chs),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("wch_add:"))
async def cb_wch_add(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        return
    bot_id = int(cb.data.split(":")[1])
    await state.set_state(BotSettingsStates.wch_add_id)
    await state.update_data(wch_bot_id=bot_id)
    await cb.message.edit_text(
        "\\u041f\\u0440\\u0438\\u0448\\u043b\\u0438 <b>chat_id \\u043a\\u0430\\u043d\\u0430\\u043b\\u0430</b> (\\u043e\\u0442\\u0440\\u0438\\u0446\\u0430\\u0442\\u0435\\u043b\\u044c\\u043d\\u043e\\u0435 \\u0447\\u0438\\u0441\\u043b\\u043e), "
        "\\u0432 \\u043a\\u043e\\u0442\\u043e\\u0440\\u043e\\u043c \\u043f\\u0440\\u0438\\u0432\\u0435\\u0442\\u043a\\u0430 \\u0434\\u043e\\u043b\\u0436\\u043d\\u0430 \\u0440\\u0430\\u0431\\u043e\\u0442\\u0430\\u0442\\u044c."
    )
    await cb.answer()


@router.message(BotSettingsStates.wch_add_id)
async def m_wch_add(message: Message, state: FSMContext, bot: Bot) -> None:
    if not is_admin(message.from_user.id):
        return
    try:
        chat_id = int((message.text or "").strip())
    except ValueError:
        await message.answer("\\u041d\\u0443\\u0436\\u043d\\u043e \\u0446\\u0435\\u043b\\u043e\\u0435 \\u0447\\u0438\\u0441\\u043b\\u043e (chat_id \\u043a\\u0430\\u043d\\u0430\\u043b\\u0430).")
        return
    data = await state.get_data()
    bot_id = data["wch_bot_id"]
    title = str(chat_id)
    try:
        chat = await bot.get_chat(chat_id)
        title = chat.title or title
    except Exception:
        pass
    await get_db().add_welcome_channel(bot_id, chat_id, title)
    await state.clear()
    chs = await get_db().list_welcome_channels(bot_id)
    await message.answer(
        f"\\u2705 \\u041a\\u0430\\u043d\\u0430\\u043b \\u00ab{title}\\u00bb \\u0434\\u043e\\u0431\\u0430\\u0432\\u043b\\u0435\\u043d.",
        reply_markup=_menu(bot_id, chs),
    )


@router.callback_query(F.data.startswith("wchv:"))
async def cb_wch_view(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        return
    wch_id = int(cb.data.split(":")[1])
    ch = await get_db().get_welcome_channel(wch_id)
    if not ch:
        await cb.answer("\\u041d\\u0435 \\u043d\\u0430\\u0439\\u0434\\u0435\\u043d\\u043e", show_alert=True)
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="\\u23f1 \\u0417\\u0430\\u0434\\u0435\\u0440\\u0436\\u043a\\u0430 \\u0441\\u0442\\u0430\\u0440\\u0442\\u0430", callback_data=f"wch_delay:{wch_id}")],
        [InlineKeyboardButton(text="\\U0001F5d1 \\u0423\\u0434\\u0430\\u043b\\u0438\\u0442\\u044c \\u043a\\u0430\\u043d\\u0430\\u043b", callback_data=f"wch_del:{wch_id}")],
        [InlineKeyboardButton(text="\\u00ab \\u041a \\u043a\\u0430\\u043d\\u0430\\u043b\\u0430\\u043c", callback_data=f"wch:{ch['bot_id']}")],
    ])
    await cb.message.edit_text(
        f"<b>\\U0001F4E2 {ch['title']}</b>\\n\\n"
        f"chat_id: <code>{ch['chat_id']}</code>\\n"
        f"\\u0417\\u0430\\u0434\\u0435\\u0440\\u0436\\u043a\\u0430 \\u0441\\u0442\\u0430\\u0440\\u0442\\u0430: <b>{ch['start_delay']} \\u0441</b>",
        reply_markup=kb,
    )
    await cb.answer()


@router.callback_query(F.data.startswith("wch_delay:"))
async def cb_wch_delay(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        return
    wch_id = int(cb.data.split(":")[1])
    await state.set_state(BotSettingsStates.wch_set_delay)
    await state.update_data(wch_id=wch_id)
    await cb.message.edit_text(
        "\\u041f\\u0440\\u0438\\u0448\\u043b\\u0438 <b>\\u0437\\u0430\\u0434\\u0435\\u0440\\u0436\\u043a\\u0443 \\u0441\\u0442\\u0430\\u0440\\u0442\\u0430</b> \\u0441\\u0446\\u0435\\u043d\\u0430\\u0440\\u0438\\u044f \\u0434\\u043b\\u044f \\u044d\\u0442\\u043e\\u0433\\u043e \\u043a\\u0430\\u043d\\u0430\\u043b\\u0430 "
        "\\u0432 \\u0441\\u0435\\u043a\\u0443\\u043d\\u0434\\u0430\\u0445 (0 \\u2014 \\u0441\\u0440\\u0430\\u0437\\u0443)."
    )
    await cb.answer()


@router.message(BotSettingsStates.wch_set_delay)
async def m_wch_delay(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return
    try:
        v = int((message.text or "").strip())
        if v < 0:
            raise ValueError
    except ValueError:
        await message.answer("\\u041d\\u0443\\u0436\\u043d\\u043e \\u0446\\u0435\\u043b\\u043e\\u0435 \\u0447\\u0438\\u0441\\u043b\\u043e (0 \\u0438\\u043b\\u0438 \\u0431\\u043e\\u043b\\u044c\\u0448\\u0435).")
        return
    data = await state.get_data()
    wch_id = data["wch_id"]
    await get_db().set_welcome_channel_delay(wch_id, v)
    ch = await get_db().get_welcome_channel(wch_id)
    await state.clear()
    chs = await get_db().list_welcome_channels(ch["bot_id"])
    await message.answer(
        f"\\u2705 \\u0417\\u0430\\u0434\\u0435\\u0440\\u0436\\u043a\\u0430 \\u043a\\u0430\\u043d\\u0430\\u043b\\u0430 \\u00ab{ch['title']}\\u00bb: {v} \\u0441.",
        reply_markup=_menu(ch["bot_id"], chs),
    )


@router.callback_query(F.data.startswith("wch_del:"))
async def cb_wch_del(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        return
    wch_id = int(cb.data.split(":")[1])
    ch = await get_db().get_welcome_channel(wch_id)
    if not ch:
        await cb.answer("\\u041d\\u0435 \\u043d\\u0430\\u0439\\u0434\\u0435\\u043d\\u043e", show_alert=True)
        return
    bot_id = ch["bot_id"]
    await get_db().delete_welcome_channel(wch_id)
    chs = await get_db().list_welcome_channels(bot_id)
    await cb.message.edit_text(
        "\\U0001F5d1 \\u041a\\u0430\\u043d\\u0430\\u043b \\u0443\\u0434\\u0430\\u043b\\u0451\\u043d.",
        reply_markup=_menu(bot_id, chs),
    )
    await cb.answer()
''', encoding="utf-8")
print("  ✓ handlers/welcome_channels.py создан")

# === 7. регистрация роутера ===
INIT = ROOT / "handlers/__init__.py"
init_src = INIT.read_text(encoding="utf-8")
if "welcome_channels" not in init_src:
    # добавляем к импорту и регистрации
    if "channel_links" in init_src:
        init_src = init_src.replace(
            "channel_links", "channel_links, welcome_channels", 1
        )
        init_src = init_src.replace(
            "dp.include_router(channel_links.router)",
            "dp.include_router(channel_links.router)\n"
            "    dp.include_router(welcome_channels.router)",
            1,
        )
    else:
        raise SystemExit("не нашёл channel_links в handlers/__init__.py — "
                         "покажи его содержимое")
    INIT.write_text(init_src, encoding="utf-8")
    print("  ✓ handlers/__init__.py — роутер welcome_channels")

print("\\n✅ Патч 27 применён. Перезапусти: systemctl restart bot")
print("\\n⚠️  ВНИМАНИЕ: пока в настройках приветки не добавлен ни один")
print("   канал — приветка НЕ отвечает на заявки. Добавь каналы:")
print("   приветка → Настройки → 📢 Каналы приветки → Добавить канал.")
