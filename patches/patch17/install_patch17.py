#!/usr/bin/env python3
"""Патч 17: статистика инвайт-ссылок канала."""
import shutil
from pathlib import Path

ROOT = Path("/opt/bot")  # для друга заменить на /opt/friend_bot
HERE = Path(__file__).resolve().parent


def patch(path: Path, old: str, new: str, label: str):
    src = path.read_text(encoding="utf-8")
    if old not in src:
        raise SystemExit(f"NOT FOUND ({label}) in {path.name}:\n---\n{old[:300]}\n---")
    src = src.replace(old, new, 1)
    path.write_text(src, encoding="utf-8")
    print(f"  ✓ {path.relative_to(ROOT)} — {label}")


# === 1. Копируем channel_links.py ===
shutil.copy(HERE / "channel_links.py", ROOT / "handlers/channel_links.py")
print("  ✓ handlers/channel_links.py")

# === 2. БД: таблица + методы ===
DB = ROOT / "database/db.py"
db_src = DB.read_text(encoding="utf-8")
if "channel_links" not in db_src:
    # таблица — добавляем перед "-- Индексы"
    db_src = db_src.replace(
        "-- Индексы\n",
        '''-- Инвайт-ссылки канала (статистика вступлений)
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

-- Индексы
''',
        1,
    )
    db_src = db_src.replace(
        "CREATE INDEX IF NOT EXISTS idx_pjr ON pending_join_requests(bot_id, channel_id, user_tg_id);",
        "CREATE INDEX IF NOT EXISTS idx_pjr ON pending_join_requests(bot_id, channel_id, user_tg_id);\n"
        "CREATE INDEX IF NOT EXISTS idx_chlinks ON channel_links(bot_id, invite_link);",
    )
    # методы — после now()
    anchor = "class DB:"
    methods = '''def _cl_noop():
    pass


'''
    # вставим методы внутрь класса DB — после первого метода. Найдём "    async def "
    idx = db_src.find("    async def ", db_src.find("class DB:"))
    cl_methods = '''    async def add_channel_link(self, bot_id, channel_id, name, invite_link):
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

'''
    db_src = db_src[:idx] + cl_methods + db_src[idx:]
    DB.write_text(db_src, encoding="utf-8")
    print("  ✓ database/db.py — таблица channel_links + методы")

# === 3. greeter.py: обработчик chat_member + заявок по invite_link ===
GR = ROOT / "bots/greeter.py"
gr_src = GR.read_text(encoding="utf-8")

# 3a. в on_join_request — считаем заявку по invite_link
if "inc_channel_link" not in gr_src:
    patch(
        GR,
        '''        # ВСЕГДА записываем заявку — потом она учтётся при проверке ОП
        await db.add_pending_join_request(
            bot_record["id"], req.chat.id, req.from_user.id
        )''',
        '''        # ВСЕГДА записываем заявку — потом она учтётся при проверке ОП
        await db.add_pending_join_request(
            bot_record["id"], req.chat.id, req.from_user.id
        )
        # Если заявка пришла по нашей инвайт-ссылке канала — считаем
        _il = getattr(req, "invite_link", None)
        if _il is not None and getattr(_il, "invite_link", None):
            try:
                await db.inc_channel_link(_il.invite_link, requested=1)
            except Exception as _e:
                log.warning("inc_channel_link (request): %s", _e)''',
        "учёт заявок по invite_link",
    )

# 3b. новый хендлер chat_member — считаем вступления
if "@dp.chat_member" not in gr_src:
    # вставляем перед регистрацией (в конце функции register_greeter_handlers).
    # Найдём строку с @dp.chat_join_request и добавим хендлер рядом.
    anchor = "    @dp.chat_join_request()"
    new_handler = '''    @dp.chat_member()
    async def on_chat_member(upd) -> None:
        """Считает вступления по инвайт-ссылкам канала."""
        try:
            db = get_db()
            bot_record = await _get_bot_record()
            if not bot_record:
                return
            il = getattr(upd, "invite_link", None)
            if il is None or not getattr(il, "invite_link", None):
                return
            old_s = upd.old_chat_member.status if upd.old_chat_member else None
            new_s = upd.new_chat_member.status if upd.new_chat_member else None
            # вступил: был left/kicked → стал member
            if new_s == "member" and old_s in ("left", "kicked", None):
                await db.inc_channel_link(il.invite_link, joined=1)
        except Exception as e:
            log.warning("on_chat_member error: %s", e)

'''
    gr_src = gr_src.replace(anchor, new_handler + anchor, 1)
    GR.write_text(gr_src, encoding="utf-8")
    print("  ✓ bots/greeter.py — обработчик chat_member")

# === 4. manager.py: добавить chat_member в allowed_updates ===
MG = ROOT / "bots/manager.py"
mg_src = MG.read_text(encoding="utf-8")
if '"chat_member"' not in mg_src:
    patch(
        MG,
        '''                            "chat_join_request",
                            "my_chat_member",''',
        '''                            "chat_join_request",
                            "my_chat_member",
                            "chat_member",''',
        "chat_member в allowed_updates",
    )

# === 5. keyboards: кнопка в меню приветки ===
KB = ROOT / "keyboards/constructor_kb.py"
patch(
    KB,
    '''        [InlineKeyboardButton(text="🔗 Реф-ссылки", callback_data=f"refs:{bot_id}")],''',
    '''        [InlineKeyboardButton(text="🔗 Реф-ссылки", callback_data=f"refs:{bot_id}")],
        [InlineKeyboardButton(text="📊 Ссылки канала", callback_data=f"chlinks:{bot_id}")],''',
    "кнопка «Ссылки канала» в меню",
)

# === 6. handlers/__init__.py: регистрация роутера ===
INIT = ROOT / "handlers/__init__.py"
init_src = INIT.read_text(encoding="utf-8")
if "channel_links" not in init_src:
    init_src = init_src.replace(
        "sponsor_edit",
        "sponsor_edit, channel_links",
        1,
    )
    init_src = init_src.replace(
        "    dp.include_router(sponsor_edit.router)",
        "    dp.include_router(sponsor_edit.router)\n    dp.include_router(channel_links.router)",
    )
    INIT.write_text(init_src, encoding="utf-8")
    print("  ✓ handlers/__init__.py — роутер channel_links")

print("\n✅ Патч 17 применён. Перезапусти бот.")
