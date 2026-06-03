#!/usr/bin/env python3
"""
Патч 4: проверка через заявки + фикс показа спонсоров.

1. Новая таблица pending_join_requests + методы доступа в БД.
2. В чек-юзера (get_unsubscribed_check_required) — учитываем заявки.
3. В _send_op_step — пропускаем шаг только если to_show пустой
   (раньше пропускался даже когда были необязательные каналы).
4. В on_join_request (greeter) — если канал помечен как спонсорский
   с request_mode, заявка записывается, но сценарий не запускается.
5. В step_create — добавлен вопрос «канал по заявкам?» при создании
   обязательного спонсора.

ВНИМАНИЕ: после запуска перезапустить бот.
"""
import re
import sys
from pathlib import Path

ROOT = Path("/opt/bot")


def patch_file(path: Path, edits: list[tuple[str, str]]) -> None:
    src = path.read_text(encoding="utf-8")
    for old, new in edits:
        if old not in src:
            raise SystemExit(f"PATTERN NOT FOUND in {path}:\n---\n{old[:200]}\n---")
        src = src.replace(old, new, 1)
    path.write_text(src, encoding="utf-8")
    print(f"  ✓ {path.relative_to(ROOT)}")


# === 1. database/db.py — миграция + методы ===
print("[1/5] database/db.py")
patch_file(ROOT / "database/db.py", [
    # Новая таблица — добавляем ПЕРЕД блоком "-- Индексы"
    ("-- Индексы\n",
     """-- Заявки на вступление в каналы (для проверки спонсоров типа «по заявкам»)
CREATE TABLE IF NOT EXISTS pending_join_requests (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    bot_id      INTEGER NOT NULL,
    channel_id  INTEGER NOT NULL,
    user_tg_id  INTEGER NOT NULL,
    created_at  INTEGER NOT NULL,
    UNIQUE(bot_id, channel_id, user_tg_id),
    FOREIGN KEY (bot_id) REFERENCES greeting_bots(id) ON DELETE CASCADE
);

-- Индексы
"""),
    # Индекс для быстрого поиска
    ("CREATE INDEX IF NOT EXISTS idx_completions ON step_completions(step_id, user_id);",
     "CREATE INDEX IF NOT EXISTS idx_completions ON step_completions(step_id, user_id);\n"
     "CREATE INDEX IF NOT EXISTS idx_pjr ON pending_join_requests(bot_id, channel_id, user_tg_id);"),
    # Методы — добавляем после record_step_completion
    ('''    async def record_step_completion(self, user_id: int, step_id: int) -> None:
        await self._conn.execute(
            "INSERT INTO step_completions (user_id, step_id, completed_at) VALUES (?, ?, ?)",''',
     '''    async def add_pending_join_request(self, bot_id: int, channel_id: int, user_tg_id: int) -> None:
        """Запоминает что юзер подал заявку в канал. Для спонсоров «по заявкам»."""
        await self._conn.execute(
            "INSERT OR IGNORE INTO pending_join_requests(bot_id, channel_id, user_tg_id, created_at) VALUES (?, ?, ?, ?)",
            (bot_id, int(channel_id), int(user_tg_id), now()),
        )
        await self._conn.commit()

    async def has_pending_join_request(self, bot_id: int, channel_id: int, user_tg_id: int) -> bool:
        cur = await self._conn.execute(
            "SELECT 1 FROM pending_join_requests WHERE bot_id=? AND channel_id=? AND user_tg_id=? LIMIT 1",
            (bot_id, int(channel_id), int(user_tg_id)),
        )
        return (await cur.fetchone()) is not None

    async def is_request_sponsor_channel(self, bot_id: int, channel_id: int) -> bool:
        """True, если у этой приветки есть шаг ОП со спонсором request_mode=True и таким channel_id."""
        import json as _json
        cur = await self._conn.execute(
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

    async def record_step_completion(self, user_id: int, step_id: int) -> None:
        await self._conn.execute(
            "INSERT INTO step_completions (user_id, step_id, completed_at) VALUES (?, ?, ?)",'''),
])


# === 2. utils/checker.py — учитываем заявки ===
print("[2/5] utils/checker.py")
patch_file(ROOT / "utils/checker.py", [
    ("async def get_unsubscribed_check_required(\n"
     "    bot: Bot, sponsors: list[dict], user_id: int\n"
     ") -> list[dict]:\n"
     "    \"\"\"Возвращает список спонсоров, на которые юзер ОБЯЗАН подписаться,\n"
     "    но ещё не подписан. Спонсоры без проверки (check=False) не учитываются.\"\"\"\n"
     "    res: list[dict] = []\n"
     "    for sp in sponsors:\n"
     "        if not sp.get(\"check\"):\n"
     "            continue\n"
     "        cid = sp.get(\"channel_id\")\n"
     "        if not cid:\n"
     "            continue\n"
     "        ok = await is_subscribed(bot, int(cid), user_id)\n"
     "        if not ok:\n"
     "            res.append(sp)\n"
     "    return res\n",
     "async def get_unsubscribed_check_required(\n"
     "    bot: Bot, sponsors: list[dict], user_id: int, *, bot_id: int | None = None\n"
     ") -> list[dict]:\n"
     "    \"\"\"Возвращает список обязательных спонсоров, которых юзер ещё не «прошёл».\n"
     "    Прошёл = подписан, либо (если канал «по заявкам») подал заявку.\"\"\"\n"
     "    from database import get_db\n"
     "    db = get_db() if bot_id is not None else None\n"
     "    res: list[dict] = []\n"
     "    for sp in sponsors:\n"
     "        if not sp.get(\"check\"):\n"
     "            continue\n"
     "        cid = sp.get(\"channel_id\")\n"
     "        if not cid:\n"
     "            continue\n"
     "        # Подписан?\n"
     "        if await is_subscribed(bot, int(cid), user_id):\n"
     "            continue\n"
     "        # Канал «по заявкам» и заявка есть?\n"
     "        if sp.get(\"request_mode\") and db is not None:\n"
     "            if await db.has_pending_join_request(bot_id, int(cid), user_id):\n"
     "                continue\n"
     "        res.append(sp)\n"
     "    return res\n"),
])


# === 3. bots/scenario.py — пропуск только если to_show пустой; пробрасываем bot_id ===
print("[3/5] bots/scenario.py")
patch_file(ROOT / "bots/scenario.py", [
    # 3a. handle_check_op — пробрасываем bot_id в get_unsubscribed_check_required
    ("        not_ok = await get_unsubscribed_check_required(bot, sponsors, user[\"tg_id\"])",
     "        not_ok = await get_unsubscribed_check_required(bot, sponsors, user[\"tg_id\"], bot_id=bot_record[\"id\"])"),
    # 3b. _send_op_step — новая логика to_show + учёт заявок
    ('''        # Спонсоры, которые надо показать (не подписан, или check=False)
        to_show: list[dict] = []
        for sp in sponsors:
            if not sp.get("check"):
                to_show.append(sp)
            else:
                from utils.checker import is_subscribed
                cid = sp.get("channel_id")
                if cid and await is_subscribed(bot, int(cid), user["tg_id"]):
                    continue
                to_show.append(sp)

        # Если все уже подписаны (или их вообще нет с check) — продвигаем дальше
        # но только если хотя бы один требовал check
        has_required = any(s.get("check") for s in sponsors)
        if has_required and not any(s.get("check") for s in to_show):
            await get_db().record_step_completion(user["id"], step["id"])
            await self.advance(bot, bot_record, user["id"])
            return -1  # маркер: ничего не отправляем, перешли дальше''',
     '''        # Спонсоры, которые надо показать.
        # - check=False → показываем всегда (это «не обязательные»)
        # - check=True  → показываем, если юзер не «прошёл» канал
        #   («прошёл» = подписан ИЛИ, если request_mode, есть заявка)
        from utils.checker import is_subscribed
        db = get_db()
        to_show: list[dict] = []
        for sp in sponsors:
            if not sp.get("check"):
                to_show.append(sp)
                continue
            cid = sp.get("channel_id")
            if not cid:
                to_show.append(sp)
                continue
            if await is_subscribed(bot, int(cid), user["tg_id"]):
                continue
            if sp.get("request_mode") and await db.has_pending_join_request(
                bot_record["id"], int(cid), user["tg_id"]
            ):
                continue
            to_show.append(sp)

        # Если показывать нечего — пропускаем шаг (все обязательные «пройдены»,
        # и необязательных нет).
        if not to_show:
            await get_db().record_step_completion(user["id"], step["id"])
            await self.advance(bot, bot_record, user["id"])
            return -1  # маркер: ничего не отправляем, перешли дальше'''),
])


# === 4. bots/greeter.py — фильтрация спонсорских заявок ===
print("[4/5] bots/greeter.py")
patch_file(ROOT / "bots/greeter.py", [
    ('''    @dp.chat_join_request()
    async def on_join_request(req: ChatJoinRequest) -> None:
        db = get_db()
        bot_record = await _get_bot_record()
        if not bot_record:
            return
        user = await db.upsert_user(
            bot_record["id"],
            req.from_user.id,
            username=req.from_user.username,
            first_name=req.from_user.first_name,
            is_premium=bool(getattr(req.from_user, "is_premium", False)),
        )
        # По умолчанию заявку не одобряем (это решает админ канала или другие боты)
        engine = get_engine()
        try:
            await engine.start_or_restart(req.bot, bot_record, user)
        except Exception as e:
            log.exception("join_request scenario error: %s", e)''',
     '''    @dp.chat_join_request()
    async def on_join_request(req: ChatJoinRequest) -> None:
        db = get_db()
        bot_record = await _get_bot_record()
        if not bot_record:
            return
        # ВСЕГДА записываем заявку — потом она учтётся при проверке ОП
        await db.add_pending_join_request(
            bot_record["id"], req.chat.id, req.from_user.id
        )
        # Если канал помечен как спонсорский «по заявкам» — НЕ запускаем
        # сценарий приветки. Иначе юзер канала-спонсора получит наш
        # приветственный сценарий, чего быть не должно.
        if await db.is_request_sponsor_channel(bot_record["id"], req.chat.id):
            log.info(
                "[bot %s] заявка в спонсорский канал %s от %s — только трекинг",
                bot_record["id"], req.chat.id, req.from_user.id,
            )
            return
        user = await db.upsert_user(
            bot_record["id"],
            req.from_user.id,
            username=req.from_user.username,
            first_name=req.from_user.first_name,
            is_premium=bool(getattr(req.from_user, "is_premium", False)),
        )
        engine = get_engine()
        try:
            await engine.start_or_restart(req.bot, bot_record, user)
        except Exception as e:
            log.exception("join_request scenario error: %s", e)'''),
])


# === 5. handlers/step_create.py — вопрос «по заявкам?» при создании спонсора ===
print("[5/5] handlers/step_create.py")
# Сначала добавим новый стейт в states/states.py
states_file = ROOT / "states/states.py"
states_src = states_file.read_text(encoding="utf-8")
if "op_sponsor_request_mode" not in states_src:
    states_src = states_src.replace(
        "op_sponsor_check = State()",
        "op_sponsor_check = State()\n    op_sponsor_request_mode = State()",
    )
    states_file.write_text(states_src, encoding="utf-8")
    print("  ✓ states/states.py")

# Теперь в step_create — после op_sponsor_check (где check=True) добавляем
# вопрос про request_mode. Если check=False — пропускаем сразу к channel_id (как было)
patch_file(ROOT / "handlers/step_create.py", [
    # 5a. Когда юзер выбрал «обязательная подписка» — теперь спрашиваем про режим
    ('''@router.callback_query(StepStates.op_sponsor_check, F.data.startswith("spc:"))''',
     '''@router.callback_query(StepStates.op_sponsor_request_mode, F.data.startswith("sprm:"))
async def cb_op_sponsor_request_mode(cb: CallbackQuery, state: FSMContext) -> None:
    val = cb.data.split(":")[1]  # "yes" | "no"
    data = await state.get_data()
    draft = data["draft"]
    draft["_current_sponsor"]["request_mode"] = (val == "yes")
    await state.update_data(draft=draft)
    await state.set_state(StepStates.op_sponsor_channel_id)
    hint = (
        "✋ Канал помечен как «по заявкам».\\n"
        "Приветка должна быть админом этого канала с правом «Приглашать пользователей»."
        if val == "yes" else
        "📺 Обычный канал — проверяем только подписку."
    )
    await cb.message.edit_text(
        hint + "\\n\\nПришли <b>chat_id</b> канала (или перешли любое сообщение из него):",
    )
    await cb.answer()


@router.callback_query(StepStates.op_sponsor_check, F.data.startswith("spc:"))'''),
    # 5b. Внутри cb_op_sponsor_check — когда выбрана обязательная подписка,
    # переходим не в op_sponsor_channel_id, а в op_sponsor_request_mode
    ('''        await state.set_state(StepStates.op_sponsor_channel_id)
        await cb.message.edit_text(
            "📺 <b>Канал/чат с обязательной подпиской</b>\\n\\n"
            "Пришли <b>chat_id</b> канала (или перешли сюда любое сообщение из него):",
        )''',
     '''        await state.set_state(StepStates.op_sponsor_request_mode)
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="📺 Обычный (только подписка)", callback_data="sprm:no"),
        ], [
            InlineKeyboardButton(text="✋ По заявкам (учитывать заявки)", callback_data="sprm:yes"),
        ]])
        await cb.message.edit_text(
            "<b>Тип канала</b>\\n\\n"
            "📺 <b>Обычный</b> — юзер должен подписаться. Бот проверяет членство.\\n\\n"
            "✋ <b>По заявкам</b> — юзер должен подать заявку. Засчитывается, "
            "даже если админ канала ещё не одобрил её.\\n"
            "<i>Требует: приветка — админ канала с правом «Приглашать через ссылки».</i>",
            reply_markup=kb,
        )'''),
])

print("\n✅ Все патчи применены. Перезапусти бот:")
print("   systemctl restart bot")
