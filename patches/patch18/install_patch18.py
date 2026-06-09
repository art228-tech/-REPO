#!/usr/bin/env python3
"""
Патч 18: статистика по инвайт-ссылкам канала.
- bot_users.channel_link_id — по какой ссылке канала пришёл юзер.
- on_join_request пишет channel_link_id, если заявка по нашей ссылке.
- В разделе «Статистика» — кнопка «По ссылкам канала» с полной
  детализацией (премиум / ОП / шаги) по каждой ссылке.
"""
import shutil
from pathlib import Path

ROOT = Path("/opt/bot")  # для друга — /opt/friend_bot


def patch(path: Path, old: str, new: str, label: str):
    src = path.read_text(encoding="utf-8")
    if old not in src:
        raise SystemExit(f"NOT FOUND ({label}) in {path.name}:\n---\n{old[:300]}\n---")
    src = src.replace(old, new, 1)
    path.write_text(src, encoding="utf-8")
    print(f"  ✓ {path.relative_to(ROOT)} — {label}")


# === 1. БД: колонка channel_link_id ===
DB = ROOT / "database/db.py"
db_src = DB.read_text(encoding="utf-8")
if "channel_link_id" not in db_src:
    db_src = db_src.replace(
        "    ref_link_id         INTEGER,",
        "    ref_link_id         INTEGER,\n    channel_link_id     INTEGER,",
        1,
    )
    DB.write_text(db_src, encoding="utf-8")
    print("  ✓ database/db.py — колонка channel_link_id в схеме")

# Миграция для существующей БД (ALTER TABLE)
import sqlite3
dbp = str(ROOT / "data.db")
if Path(dbp).exists():
    conn = sqlite3.connect(dbp)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(bot_users)").fetchall()]
    if "channel_link_id" not in cols:
        conn.execute("ALTER TABLE bot_users ADD COLUMN channel_link_id INTEGER")
        conn.commit()
        print("  ✓ data.db — колонка channel_link_id добавлена в существующую БД")
    conn.close()

# === 2. метод set_user_channel_link ===
db_src = DB.read_text(encoding="utf-8")
if "set_user_channel_link" not in db_src:
    idx = db_src.find("    async def upsert_user(")
    method = '''    async def set_user_channel_link(self, bot_id: int, tg_id: int, channel_link_id: int):
        """Помечает, по какой инвайт-ссылке канала пришёл юзер (если ещё не помечен)."""
        await self.conn.execute(
            "UPDATE bot_users SET channel_link_id=? "
            "WHERE bot_id=? AND tg_id=? AND channel_link_id IS NULL",
            (channel_link_id, bot_id, tg_id),
        )
        await self.conn.commit()

    '''
    db_src = db_src[:idx] + method + db_src[idx:]
    DB.write_text(db_src, encoding="utf-8")
    print("  ✓ database/db.py — метод set_user_channel_link")

# === 3. greeter.py: в on_join_request писать channel_link_id ===
GR = ROOT / "bots/greeter.py"
gr_src = GR.read_text(encoding="utf-8")
if "set_user_channel_link" not in gr_src:
    patch(
        GR,
        '''        user = await db.upsert_user(
            bot_record["id"],
            req.from_user.id,
            username=req.from_user.username,
            first_name=req.from_user.first_name,
            is_premium=bool(getattr(req.from_user, "is_premium", False)),
        )
        engine = get_engine()''',
        '''        user = await db.upsert_user(
            bot_record["id"],
            req.from_user.id,
            username=req.from_user.username,
            first_name=req.from_user.first_name,
            is_premium=bool(getattr(req.from_user, "is_premium", False)),
        )
        # Если заявка по нашей инвайт-ссылке канала — привяжем юзера к ней
        _il = getattr(req, "invite_link", None)
        if _il is not None and getattr(_il, "invite_link", None):
            try:
                _cl = await db.get_channel_link_by_url(_il.invite_link)
                if _cl:
                    await db.set_user_channel_link(
                        bot_record["id"], req.from_user.id, _cl["id"]
                    )
            except Exception as _e:
                log.warning("set_user_channel_link: %s", _e)
        engine = get_engine()''',
        "привязка юзера к ссылке канала",
    )

# === 4. кнопка в меню статистики ===
KB = ROOT / "keyboards/constructor_kb.py"
patch(
    KB,
    '''        [InlineKeyboardButton(text="🔗 По реф-ссылкам", callback_data=f"st_refs:{bot_id}")],''',
    '''        [InlineKeyboardButton(text="🔗 По реф-ссылкам", callback_data=f"st_refs:{bot_id}")],
        [InlineKeyboardButton(text="📊 По ссылкам канала", callback_data=f"st_chl:{bot_id}")],''',
    "кнопка «По ссылкам канала»",
)

# === 5. handlers/stats.py: хендлеры st_chl ===
ST = ROOT / "handlers/stats.py"
st_src = ST.read_text(encoding="utf-8")
if "st_chl" not in st_src:
    # Добавляем перед последним роутером (после cb_stats_refs или в конец).
    # Вставим в самый конец файла.
    new_handlers = '''


@router.callback_query(F.data.startswith("st_chl:"))
async def cb_stats_channel_links(cb: CallbackQuery) -> None:
    """Список инвайт-ссылок канала со сводкой по каждой."""
    if not is_admin(cb.from_user.id):
        await cb.answer("⛔", show_alert=True)
        return
    bot_id = int(cb.data.split(":")[1])
    db = get_db()
    links = await db.list_channel_links(bot_id)
    users = await db.list_users(bot_id)
    if not links:
        from keyboards.constructor_kb import stats_menu
        await cb.message.edit_text(
            "📊 Ссылок канала ещё нет. Создай их в меню приветки → «Ссылки канала».",
            reply_markup=stats_menu(bot_id),
        )
        await cb.answer()
        return

    by_link: dict = {}
    for u in users:
        clid = u["channel_link_id"]
        if clid:
            by_link.setdefault(clid, []).append(u)

    rows = []
    text = "<b>📊 Статистика по ссылкам канала</b>\\n\\n"
    for l in links:
        ul = by_link.get(l["id"], [])
        total = len(ul)
        text += f"<b>{l['name']}</b>\\n"
        text += f"   ✅ Принято заявок: {l['joined_count']}\\n"
        if total > 0:
            n_prem = sum(1 for u in ul if u["is_premium"])
            n_done = sum(1 for u in ul if u["completed"])
            text += f"   👥 Дошло до бота: {total} | ⭐ {n_prem} | 🏁 {n_done}\\n"
        text += "\\n"
        rows.append([InlineKeyboardButton(
            text=f"🔎 {l['name']}", callback_data=f"st_chlv:{l['id']}")])

    from keyboards.constructor_kb import stats_menu
    rows.append([InlineKeyboardButton(text="« Назад", callback_data=f"stat:{bot_id}")])
    await cb.message.edit_text(
        text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)
    )
    await cb.answer()


@router.callback_query(F.data.startswith("st_chlv:"))
async def cb_stats_channel_link_detail(cb: CallbackQuery) -> None:
    """Полная статистика (премиум/ОП/шаги) по одной ссылке канала."""
    if not is_admin(cb.from_user.id):
        return
    link_id = int(cb.data.split(":")[1])
    db = get_db()
    link = await db.get_channel_link(link_id)
    if not link:
        await cb.answer("Не найдено", show_alert=True)
        return
    bot_id = link["bot_id"]
    users = await db.list_users(bot_id)
    steps = await db.list_steps(bot_id)
    ul = [u for u in users if u["channel_link_id"] == link_id]
    total = len(ul)

    text = f"<b>📊 {link['name']}</b>\\n\\n"
    text += f"✅ Принято заявок: <b>{link['joined_count']}</b>\\n\\n"
    if total == 0:
        text += "Пока никто из пришедших по ссылке не дошёл до бота."
    else:
        n_alive = sum(1 for u in ul if u["is_alive"])
        n_prem = sum(1 for u in ul if u["is_premium"])
        n_done = sum(1 for u in ul if u["completed"])
        text += (
            f"👥 Дошло до бота: <b>{total}</b>\\n"
            f"🟢 Живых: {n_alive} ({n_alive*100//total}%)\\n"
            f"🪦 Мёртвых: {total-n_alive} ({(total-n_alive)*100//total}%)\\n"
            f"⭐️ Премиум: {n_prem} ({n_prem*100//total}%)\\n"
            f"🏁 Прошли сценарий: {n_done} ({n_done*100//total}%)\\n"
        )
        if steps:
            text += "\\n<b>📜 По шагам:</b>\\n"
            type_emoji = {"roulette": "🎰", "op": "📢", "message": "💬"}
            uids = [u["id"] for u in ul]
            ph = ",".join("?" * len(uids))
            for s in steps:
                cur = await db.conn.execute(
                    f"SELECT COUNT(DISTINCT user_id) FROM step_completions "
                    f"WHERE step_id=? AND user_id IN ({ph})",
                    [s["id"]] + uids,
                )
                cnt = (await cur.fetchone())[0]
                pct = cnt * 100 // total if total else 0
                e = type_emoji.get(s["step_type"], "·")
                text += f"{s['step_order']+1}. {e} {s['step_type']}: {cnt}/{total} ({pct}%)\\n"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="« К списку ссылок", callback_data=f"st_chl:{bot_id}")],
    ])
    await cb.message.edit_text(text, reply_markup=kb)
    await cb.answer()
'''
    # убедимся что нужные импорты есть
    if "InlineKeyboardButton" not in st_src or "InlineKeyboardMarkup" not in st_src:
        # добавим импорт
        st_src = st_src.replace(
            "from aiogram.types import",
            "from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup,",
            1,
        )
    st_src = st_src + new_handlers
    ST.write_text(st_src, encoding="utf-8")
    print("  ✓ handlers/stats.py — хендлеры st_chl / st_chlv")

print("\n✅ Патч 18 применён. Перезапусти бот.")
