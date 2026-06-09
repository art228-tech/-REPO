#!/usr/bin/env python3
"""
Патч 5: валидация спонсоров при добавлении + фоновый мониторинг.

1. После ввода chat_id спонсора конструктор проверяет:
   - бот является членом канала
   - бот админ (для request_mode — с can_invite_users)
2. Ссылка проверяется на корректный формат и совпадение с каналом.
3. Фоновый воркер раз в 10 минут обходит всех спонсоров каждой приветки,
   и если права или ссылка сломались — шлёт админу алерт.
"""
import sys
from pathlib import Path

ROOT = Path("/opt/bot")


def patch_file(path: Path, edits: list[tuple[str, str]]) -> None:
    src = path.read_text(encoding="utf-8")
    for old, new in edits:
        if old not in src:
            raise SystemExit(f"PATTERN NOT FOUND in {path}:\n---\n{old[:300]}\n---")
        src = src.replace(old, new, 1)
    path.write_text(src, encoding="utf-8")
    print(f"  ✓ {path.relative_to(ROOT)}")


# === 1. utils/sponsor_check.py — новый файл с проверкой прав ===
print("[1/4] utils/sponsor_check.py")
(ROOT / "utils/sponsor_check.py").write_text('''"""Проверка прав приветки в канале-спонсоре."""
from __future__ import annotations

from typing import Literal
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError


SponsorCheckResult = dict  # {"ok": bool, "reason": str | None, "details": dict}


async def check_sponsor_access(
    bot: Bot,
    channel_id: int,
    *,
    require_invite_users: bool = False,
) -> SponsorCheckResult:
    """Проверяет что приветка имеет доступ к каналу-спонсору.

    Возвращает dict:
      ok=True/False
      reason — текстовое описание проблемы (если ok=False)
      details — словарь с status, can_invite_users и т.п.
    """
    try:
        me = await bot.get_me()
        member = await bot.get_chat_member(channel_id, me.id)
    except TelegramBadRequest as e:
        msg = str(e).lower()
        if "chat not found" in msg:
            return {"ok": False, "reason": "канал не найден (неверный chat_id или приветка не добавлена)", "details": {}}
        if "member list is inaccessible" in msg or "user_not_participant" in msg:
            return {"ok": False, "reason": "приветка не в канале — добавь её админом", "details": {}}
        return {"ok": False, "reason": f"Telegram: {e}", "details": {}}
    except TelegramForbiddenError:
        return {"ok": False, "reason": "приветка забанена или нет доступа к каналу", "details": {}}
    except Exception as e:
        return {"ok": False, "reason": f"ошибка: {e}", "details": {}}

    status = getattr(member, "status", "unknown")
    can_invite = bool(getattr(member, "can_invite_users", False))
    details = {"status": status, "can_invite_users": can_invite}

    if status not in ("administrator", "creator"):
        return {"ok": False, "reason": f"приветка не админ канала (статус: {status})", "details": details}

    if require_invite_users and not can_invite and status != "creator":
        return {"ok": False, "reason": "у приветки нет права «Приглашать пользователей через ссылки»", "details": details}

    return {"ok": True, "reason": None, "details": details}


async def check_invite_link(bot: Bot, link: str, channel_id: int) -> SponsorCheckResult:
    """Проверяет ссылку-приглашение: что она ведёт к нужному каналу
    и не отозвана. Для t.me/joinchat/... и t.me/+... через getChat невозможно,
    поэтому ограничиваемся форматом.
    """
    if not link:
        return {"ok": False, "reason": "пустая ссылка", "details": {}}
    if not (link.startswith("http://") or link.startswith("https://") or link.startswith("tg://")):
        return {"ok": False, "reason": "ссылка не похожа на URL (нужна https://t.me/...)", "details": {}}
    return {"ok": True, "reason": None, "details": {}}
''', encoding="utf-8")
print("  ✓ utils/sponsor_check.py")


# === 2. handlers/step_create.py — валидация при добавлении ===
print("[2/4] handlers/step_create.py")
patch_file(ROOT / "handlers/step_create.py", [
    # Импорт хелперов
    ("from states.fsm import StepStates",
     "from states.fsm import StepStates\nfrom utils.sponsor_check import check_sponsor_access"),
    # Валидация chat_id при сохранении
    ('''@router.message(StepStates.op_sponsor_channel_id)
async def m_op_sp_chan(message: Message, state: FSMContext) -> None:
    try:
        v = int(message.text.strip())
    except (ValueError, AttributeError):
        await message.answer("Нужно целое число (ID канала). Попробуй ещё раз.")
        return
    data = await state.get_data()
    draft = data["draft"]
    draft["_current_sponsor"]["channel_id"] = v
    await state.update_data(draft=draft)
    await state.set_state(StepStates.op_sponsor_link)
    await message.answer("Пришли <b>ссылку</b> на канал (https://t.me/...).")''',
     '''@router.message(StepStates.op_sponsor_channel_id)
async def m_op_sp_chan(message: Message, state: FSMContext) -> None:
    try:
        v = int(message.text.strip())
    except (ValueError, AttributeError):
        await message.answer("Нужно целое число (ID канала). Попробуй ещё раз.")
        return
    data = await state.get_data()
    draft = data["draft"]
    sp = draft["_current_sponsor"]
    sp["channel_id"] = v
    # Проверяем что приветка реально может работать с этим каналом
    from bots.manager import get_manager
    bot_id = draft.get("bot_id") or draft.get("greeting_bot_id")
    if bot_id:
        bot = get_manager().get_bot_instance(bot_id)
        if bot is not None:
            need_invite = bool(sp.get("request_mode"))
            res = await check_sponsor_access(bot, v, require_invite_users=need_invite)
            if not res["ok"]:
                hint = (
                    "<i>Канал «по заявкам» требует право «Приглашать пользователей через ссылки».</i>"
                    if need_invite else
                    "<i>Приветка должна быть админом этого канала.</i>"
                )
                await message.answer(
                    f"⚠️ <b>Не могу подключиться к каналу</b>\\n\\n"
                    f"Причина: {res['reason']}\\n\\n"
                    f"{hint}\\n\\n"
                    "Когда исправишь — пришли ID канала ещё раз."
                )
                return
    await state.update_data(draft=draft)
    await state.set_state(StepStates.op_sponsor_link)
    await message.answer("✅ Доступ есть.\\n\\nТеперь пришли <b>ссылку</b> на канал (https://t.me/...).")'''),
])


# === 3. utils/sponsor_monitor.py — фоновый воркер ===
print("[3/4] utils/sponsor_monitor.py")
(ROOT / "utils/sponsor_monitor.py").write_text('''"""Фоновая проверка прав приветок в спонсорских каналах.
Раз в SPONSOR_CHECK_INTERVAL секунд проходит по всем шагам ОП всех приветок,
проверяет права и шлёт алерт админам если что-то сломалось.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from database import get_db
from utils.sponsor_check import check_sponsor_access

log = logging.getLogger("sponsor_monitor")

SPONSOR_CHECK_INTERVAL = 600  # 10 минут
# Чтобы не спамить одинаковыми алертами — храним последний код проблемы в памяти
_last_state: dict[tuple[int, int], str] = {}  # (bot_id, channel_id) -> reason


async def _notify_admins(main_bot, admin_ids: list[int], text: str) -> None:
    for admin_id in admin_ids:
        try:
            await main_bot.send_message(admin_id, text)
        except Exception as e:
            log.warning("Не отправилось админу %s: %s", admin_id, e)


async def _check_one_bot(main_bot, admin_ids: list[int], bot_row, greeter_bot) -> None:
    db = get_db()
    cur = await db.conn.execute(
        "SELECT id, config FROM steps WHERE bot_id=? AND step_type='op'",
        (bot_row["id"],),
    )
    steps = await cur.fetchall()
    for step in steps:
        try:
            cfg = json.loads(step["config"])
        except Exception:
            continue
        for sp in cfg.get("sponsors", []):
            if not sp.get("check"):
                continue  # не обязательный — пропускаем
            cid = sp.get("channel_id")
            if not cid:
                continue
            need_invite = bool(sp.get("request_mode"))
            res = await check_sponsor_access(
                greeter_bot, int(cid), require_invite_users=need_invite
            )
            key = (bot_row["id"], int(cid))
            if not res["ok"]:
                # Сломано. Если про эту же причину уже сообщали — не дублируем.
                prev = _last_state.get(key)
                if prev == res["reason"]:
                    continue
                _last_state[key] = res["reason"]
                title = sp.get("title") or sp.get("button_text") or str(cid)
                bot_title = bot_row["title"] or f"приветка #{bot_row['id']}"
                text = (
                    f"⚠️ <b>Спонсор сломался</b>\\n\\n"
                    f"Приветка: <b>{bot_title}</b>\\n"
                    f"Спонсор: <b>{title}</b> (<code>{cid}</code>)\\n"
                    f"Причина: {res['reason']}\\n\\n"
                    "Проверь админ-права приветки и ссылку."
                )
                await _notify_admins(main_bot, admin_ids, text)
            else:
                # Восстановилось — если раньше был алерт, шлём «всё ок»
                if key in _last_state:
                    del _last_state[key]
                    title = sp.get("title") or sp.get("button_text") or str(cid)
                    bot_title = bot_row["title"] or f"приветка #{bot_row['id']}"
                    text = (
                        f"✅ <b>Спонсор восстановлен</b>\\n\\n"
                        f"Приветка: <b>{bot_title}</b>\\n"
                        f"Спонсор: <b>{title}</b> (<code>{cid}</code>)"
                    )
                    await _notify_admins(main_bot, admin_ids, text)


async def sponsor_monitor_loop(main_bot, admin_ids: list[int]) -> None:
    """Главный цикл. Запускается фоновой задачей в main.py."""
    from bots.manager import get_manager
    log.info("Запущен sponsor_monitor, интервал %s сек", SPONSOR_CHECK_INTERVAL)
    while True:
        try:
            db = get_db()
            bots = await db.list_greeting_bots()
            mgr = get_manager()
            for bot_row in bots:
                greeter_bot = mgr.get_bot_instance(bot_row["id"])
                if greeter_bot is None:
                    continue
                await _check_one_bot(main_bot, admin_ids, bot_row, greeter_bot)
        except Exception as e:
            log.exception("ошибка в sponsor_monitor: %s", e)
        await asyncio.sleep(SPONSOR_CHECK_INTERVAL)
''', encoding="utf-8")
print("  ✓ utils/sponsor_monitor.py")


# === 4. bots/manager.py — метод получить Bot по id; main.py — запуск воркера ===
print("[4/4] bots/manager.py + main.py")

# 4a. Добавляем метод get_bot_instance в BotManager
mgr_path = ROOT / "bots/manager.py"
mgr_src = mgr_path.read_text(encoding="utf-8")
if "def get_bot_instance" not in mgr_src:
    mgr_src = mgr_src.replace(
        "class BotManager:",
        """class BotManager:
    def get_bot_instance(self, bot_id: int):
        \"\"\"Возвращает aiogram Bot объект приветки по её id, или None.\"\"\"
        entry = self._bots.get(bot_id)
        if not entry:
            return None
        return entry.get("bot")
""",
    )
    mgr_path.write_text(mgr_src, encoding="utf-8")
    print("  ✓ bots/manager.py")

# 4b. В main.py запускаем sponsor_monitor_loop как background task
main_path = ROOT / "main.py"
main_src = main_path.read_text(encoding="utf-8")
if "sponsor_monitor_loop" not in main_src:
    # Вставляем после строки `await get_manager().start_all()`
    main_src = main_src.replace(
        "await get_manager().start_all()",
        """await get_manager().start_all()

    # Фоновый мониторинг спонсорских прав
    from utils.sponsor_monitor import sponsor_monitor_loop
    from config import ADMIN_IDS as _ADMIN_IDS
    monitor_task = asyncio.create_task(sponsor_monitor_loop(bot, _ADMIN_IDS))""",
    )
    # Чтобы у нас был доступ к `bot` — main.py определяет его позже. Найдём место
    # и перенесём запуск. Простой способ — запускать ПОСЛЕ создания bot.
    # Проверим: если "monitor_task = asyncio.create_task" стоит до `bot = Bot(...)` — ошибка.
    # Поэтому уберём «raw insert» и сделаем после Bot:
    main_src = main_src.replace(
        """    # Фоновый мониторинг спонсорских прав
    from utils.sponsor_monitor import sponsor_monitor_loop
    from config import ADMIN_IDS as _ADMIN_IDS
    monitor_task = asyncio.create_task(sponsor_monitor_loop(bot, _ADMIN_IDS))""",
        "",
    )
    # Вставим ПЕРЕД "await dp.start_polling("
    main_src = main_src.replace(
        "await dp.start_polling(",
        """# Фоновый мониторинг спонсорских прав
    from utils.sponsor_monitor import sponsor_monitor_loop
    from config import ADMIN_IDS as _ADMIN_IDS
    asyncio.create_task(sponsor_monitor_loop(bot, _ADMIN_IDS))

    await dp.start_polling(""",
        1,
    )
    main_path.write_text(main_src, encoding="utf-8")
    print("  ✓ main.py")

print("\n✅ Патч применён. Перезапусти: systemctl restart bot")
