#!/usr/bin/env python3
"""
Патч 19: режим приветки «имитация печати».
- greeting_bots.typing_mode (0/1) — вид приветки.
- В настройках приветки — переключатель «Обычная / С имитацией печати».
- Перед каждым шагом сценария (если режим включён) бот показывает
  статус (печатает / записывает видео / записывает голосовое — по типу
  контента шага) и держит паузу 5-8 секунд.
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


# === 1. БД: колонка typing_mode ===
DB = ROOT / "database/db.py"
db_src = DB.read_text(encoding="utf-8")
if "typing_mode" not in db_src:
    # в схему greeting_bots
    db_src = db_src.replace(
        "    is_active",
        "    typing_mode         INTEGER DEFAULT 0,\n    is_active",
        1,
    )
    DB.write_text(db_src, encoding="utf-8")
    print("  ✓ database/db.py — typing_mode в схеме")

# миграция существующей БД
dbp = str(ROOT / "data.db")
if Path(dbp).exists():
    conn = sqlite3.connect(dbp)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(greeting_bots)").fetchall()]
    if "typing_mode" not in cols:
        conn.execute("ALTER TABLE greeting_bots ADD COLUMN typing_mode INTEGER DEFAULT 0")
        conn.commit()
        print("  ✓ data.db — колонка typing_mode добавлена")
    conn.close()

# === 2. update_greeting_bot_settings — поддержка typing_mode ===
db_src = DB.read_text(encoding="utf-8")
if "typing_mode" in db_src and "typing_mode is not None" not in db_src:
    patch(
        DB,
        '''        self, bot_id: int, *, join_delay: int | None = None, delete_timer: int | None = None
    ) -> None:
        sets, params = [], []
        if join_delay is not None:
            sets.append("join_delay = ?")
            params.append(join_delay)''',
        '''        self, bot_id: int, *, join_delay: int | None = None, delete_timer: int | None = None,
        typing_mode: int | None = None
    ) -> None:
        sets, params = [], []
        if join_delay is not None:
            sets.append("join_delay = ?")
            params.append(join_delay)
        if typing_mode is not None:
            sets.append("typing_mode = ?")
            params.append(typing_mode)''',
        "update_greeting_bot_settings + typing_mode",
    )

# === 3. settings_menu — кнопка переключения вида ===
KB = ROOT / "keyboards/constructor_kb.py"
patch(
    KB,
    '''def settings_menu(bot_id: int, join_delay: int, delete_timer: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"⏱ Задержка перед стартом: {join_delay} с",
            callback_data=f"set_jd:{bot_id}",
        )],
        [InlineKeyboardButton(
            text=f"🗑 Таймер удаления старых: {delete_timer} с",
            callback_data=f"set_dt:{bot_id}",
        )],
        [InlineKeyboardButton(text="« Назад", callback_data=f"bot:{bot_id}")],''',
    '''def settings_menu(bot_id: int, join_delay: int, delete_timer: int,
                  typing_mode: int = 0) -> InlineKeyboardMarkup:
    _tm = "✍️ С имитацией печати" if typing_mode else "💬 Обычная"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"⏱ Задержка перед стартом: {join_delay} с",
            callback_data=f"set_jd:{bot_id}",
        )],
        [InlineKeyboardButton(
            text=f"🗑 Таймер удаления старых: {delete_timer} с",
            callback_data=f"set_dt:{bot_id}",
        )],
        [InlineKeyboardButton(
            text=f"Вид приветки: {_tm}",
            callback_data=f"set_tm:{bot_id}",
        )],
        [InlineKeyboardButton(text="« Назад", callback_data=f"bot:{bot_id}")],''',
    "кнопка вида приветки в settings_menu",
)

# === 4. bot_menu.py: все вызовы settings_menu + хендлер set_tm ===
BM = ROOT / "handlers/bot_menu.py"
bm_src = BM.read_text(encoding="utf-8")
# 4a. прокидываем typing_mode во все вызовы settings_menu(...)
bm_src = bm_src.replace(
    'settings_menu(bot_id, b["join_delay"], b["delete_timer"])',
    'settings_menu(bot_id, b["join_delay"], b["delete_timer"], b["typing_mode"])',
)
# 4b. в карточку настроек добавим строку про вид
bm_src = bm_src.replace(
    'f"🗑 Таймер удаления: <b>{b[\'delete_timer\']} с</b>\\n"',
    'f"🗑 Таймер удаления: <b>{b[\'delete_timer\']} с</b>\\n"\n'
    '        f"✍️ Вид: <b>{\'с имитацией печати\' if b[\'typing_mode\'] else \'обычная\'}</b>\\n"',
)
BM.write_text(bm_src, encoding="utf-8")
print("  ✓ handlers/bot_menu.py — settings_menu с typing_mode")

# 4c. хендлер переключения set_tm — добавляем в конец файла
bm_src = BM.read_text(encoding="utf-8")
if "set_tm" not in bm_src:
    handler = '''


@router.callback_query(F.data.startswith("set_tm:"))
async def cb_toggle_typing_mode(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        await cb.answer("\\u26d4", show_alert=True)
        return
    bot_id = int(cb.data.split(":")[1])
    db = get_db()
    b = await db.get_greeting_bot(bot_id)
    new_mode = 0 if b["typing_mode"] else 1
    await db.update_greeting_bot_settings(bot_id, typing_mode=new_mode)
    b = await db.get_greeting_bot(bot_id)
    from keyboards.constructor_kb import settings_menu
    await cb.message.edit_reply_markup(
        reply_markup=settings_menu(bot_id, b["join_delay"], b["delete_timer"], b["typing_mode"])
    )
    await cb.answer("Вид: " + ("с имитацией печати" if new_mode else "обычная"))
'''
    bm_src = bm_src + handler
    BM.write_text(bm_src, encoding="utf-8")
    print("  ✓ handlers/bot_menu.py — хендлер set_tm")

# === 5. scenario.py: показ статуса перед шагом ===
SN = ROOT / "bots/scenario.py"
patch(
    SN,
    '''        cfg = json.loads(step["config"])
        step_type = step["step_type"]

        msg_id: Optional[int] = None

        if step_type == "roulette":''',
    '''        cfg = json.loads(step["config"])
        step_type = step["step_type"]

        # Режим «имитация печати»: показываем chat action и держим паузу.
        if bot_record["typing_mode"]:
            import random as _rnd
            # тип действия по контенту шага
            if cfg.get("video_file_id") or cfg.get("animation_file_id"):
                _action = "record_video"
            elif cfg.get("sticker_file_id"):
                _action = "choose_sticker"
            elif cfg.get("voice_file_id"):
                _action = "record_voice"
            else:
                _action = "typing"
            _delay = _rnd.uniform(5, 8)
            try:
                # chat action живёт 5 сек — шлём, ждём, при нужде повторяем
                user_chat = user["tg_id"]
                await bot.send_chat_action(user_chat, _action)
                _waited = 0.0
                while _waited < _delay:
                    _chunk = min(4.0, _delay - _waited)
                    await asyncio.sleep(_chunk)
                    _waited += _chunk
                    if _waited < _delay:
                        await bot.send_chat_action(user_chat, _action)
            except Exception as _e:
                log.warning("send_chat_action: %s", _e)

        msg_id: Optional[int] = None

        if step_type == "roulette":''',
    "показ chat action перед шагом",
)

print("\\n✅ Патч 19 применён. Перезапусти бот.")
