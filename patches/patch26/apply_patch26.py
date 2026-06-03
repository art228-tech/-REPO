#!/usr/bin/env python3
"""
Патч 26: если оригинал скопированного поста удалён —
шаг помечается ⚠️ в списке сценария и ПРОПУСКАЕТСЯ (сценарий идёт дальше),
а не вешает весь сценарий.
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


HL = ROOT / "utils/helpers.py"
SN = ROOT / "bots/scenario.py"
KB = ROOT / "keyboards/constructor_kb.py"
DB = ROOT / "database/db.py"

# === 1. БД: колонка copy_broken + миграция ===
db_src = DB.read_text(encoding="utf-8")
if "copy_broken" not in db_src:
    # в схему steps
    db_src = db_src.replace(
        "CREATE TABLE IF NOT EXISTS steps",
        "CREATE TABLE IF NOT EXISTS steps", 1,
    )  # no-op, схему не трогаем — добавим только ALTER
    DB.write_text(db_src, encoding="utf-8")

dbp = str(ROOT / "data.db")
if Path(dbp).exists():
    conn = sqlite3.connect(dbp)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(steps)").fetchall()]
    if "copy_broken" not in cols:
        conn.execute("ALTER TABLE steps ADD COLUMN copy_broken INTEGER DEFAULT 0")
        conn.commit()
        print("  ✓ data.db — колонка copy_broken добавлена")
    conn.close()

# метод пометки
db_src = DB.read_text(encoding="utf-8")
if "mark_copy_broken" not in db_src:
    idx = db_src.find("    async def get_step_by_order(")
    if idx == -1:
        idx = db_src.find("class DB:") + len("class DB:") + 1
        idx = db_src.find("    async def ", idx)
    method = (
        "    async def mark_copy_broken(self, step_id: int, broken: int = 1):\n"
        '        """Помечает шаг как «оригинал копии удалён»."""\n'
        "        await self.conn.execute(\n"
        '            "UPDATE steps SET copy_broken=? WHERE id=?", (broken, step_id)\n'
        "        )\n"
        "        await self.conn.commit()\n"
        "\n"
    )
    db_src = db_src[:idx] + method + db_src[idx:]
    DB.write_text(db_src, encoding="utf-8")
    print("  ✓ database/db.py — метод mark_copy_broken")

# === 2. helpers: спец-исключение CopyOriginGone ===
hl_src = HL.read_text(encoding="utf-8")
if "CopyOriginGone" not in hl_src:
    # класс исключения — после импортов
    anchor = "log = logging.getLogger"
    if anchor in hl_src:
        hl_src = hl_src.replace(
            anchor,
            'class CopyOriginGone(Exception):\n'
            '    """Оригинал скопированного поста удалён/недоступен."""\n\n\n'
            + anchor,
            1,
        )
    else:
        # запасной вариант — в начало после первого импорта
        hl_src = "class CopyOriginGone(Exception):\n    pass\n\n\n" + hl_src

    # ловим ошибку копирования в блоке copy_message
    old_copy = '''        if copy_from and copy_from.get("chat_id") and copy_from.get("message_id"):
            msg = await bot.copy_message(
                chat_id=chat_id,
                from_chat_id=copy_from["chat_id"],
                message_id=copy_from["message_id"],
                reply_markup=reply_markup,
            )
            return msg.message_id'''
    new_copy = '''        if copy_from and copy_from.get("chat_id") and copy_from.get("message_id"):
            try:
                msg = await bot.copy_message(
                    chat_id=chat_id,
                    from_chat_id=copy_from["chat_id"],
                    message_id=copy_from["message_id"],
                    reply_markup=reply_markup,
                )
            except TelegramBadRequest as _e:
                if "message to copy not found" in str(_e).lower():
                    raise CopyOriginGone()
                raise
            return msg.message_id'''
    if old_copy not in hl_src:
        raise SystemExit("блок copy_message не совпал в helpers.py")
    hl_src = hl_src.replace(old_copy, new_copy, 1)
    HL.write_text(hl_src, encoding="utf-8")
    print("  ✓ utils/helpers.py — исключение CopyOriginGone")

# === 3. scenario: ловим CopyOriginGone в _send_message_step ===
sn_src = SN.read_text(encoding="utf-8")
if "CopyOriginGone" not in sn_src:
    # импорт
    sn_src = sn_src.replace(
        "    send_step_message,",
        "    send_step_message,\n    CopyOriginGone,",
        1,
    )
    # ловим в блоке отправки message-шага
    old_try = '''        try:
            return await send_step_message(
                bot,
                user["tg_id"],
                text=text,
                photo_file_id=photo,
                sticker_file_id=sticker,
                animation_file_id=animation,
                video_file_id=video,
                document_file_id=document,
                copy_from=copy_from,
                reply_markup=markup,
                keyboard_markup=keyboard_markup,
            )
        except TelegramForbiddenError:
            await get_db().mark_user_dead(user["id"])
            return None'''
    new_try = '''        try:
            return await send_step_message(
                bot,
                user["tg_id"],
                text=text,
                photo_file_id=photo,
                sticker_file_id=sticker,
                animation_file_id=animation,
                video_file_id=video,
                document_file_id=document,
                copy_from=copy_from,
                reply_markup=markup,
                keyboard_markup=keyboard_markup,
            )
        except TelegramForbiddenError:
            await get_db().mark_user_dead(user["id"])
            return None
        except CopyOriginGone:
            # Оригинал копии удалён — помечаем шаг и пропускаем его,
            # чтобы один мёртвый пост не вешал весь сценарий.
            await get_db().mark_copy_broken(step["id"], 1)
            log.warning("[bot %s] шаг %s: оригинал копии удалён — пропускаем",
                        bot_record["id"], step["id"])
            await get_db().record_step_completion(user["id"], step["id"])
            asyncio.create_task(self.advance(bot, bot_record, user["id"]))
            return -1'''
    if old_try not in sn_src:
        raise SystemExit("блок send_step_message не совпал в scenario.py")
    sn_src = sn_src.replace(old_try, new_try, 1)
    SN.write_text(sn_src, encoding="utf-8")
    print("  ✓ bots/scenario.py — обработка CopyOriginGone")

# === 4. keyboards: ⚠️ в списке шагов ===
patch(
    KB,
    '''    for s in steps:
        emoji = type_emoji.get(s["step_type"], "·")
        rows.append([InlineKeyboardButton(
            text=f"{s['step_order']+1}. {emoji} {s['step_type']}",
            callback_data=f"step:{s['id']}",
        )])''',
    '''    for s in steps:
        emoji = type_emoji.get(s["step_type"], "·")
        # ⚠️ — оригинал скопированного поста удалён
        try:
            broken = s["copy_broken"]
        except (KeyError, IndexError):
            broken = 0
        warn = " ⚠️ оригинал удалён" if broken else ""
        rows.append([InlineKeyboardButton(
            text=f"{s['step_order']+1}. {emoji} {s['step_type']}{warn}",
            callback_data=f"step:{s['id']}",
        )])''',
    "⚠️ в списке шагов сценария",
)

print("\\n✅ Патч 26 применён. Перезапусти: systemctl restart bot")
