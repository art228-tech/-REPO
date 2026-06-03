#!/usr/bin/env python3
"""
Патч автопостера v2 #1: редактирование ссылок в постах.

В карточке поста — кнопка «🔗 Ссылки».
Показывает уникальные ссылки из текста (внутри <a href="...">) и из кнопок.
Тап на ссылку → бот просит новую → меняет ВЕЗДЕ (в тексте и кнопках)
по точному совпадению.
Для пересланных постов (copy_from) не работает — там контент чужой.
"""
import re
from pathlib import Path

ROOT = Path("/opt/autoposter")


def patch(path: Path, old: str, new: str, label: str):
    src = path.read_text(encoding="utf-8")
    if old not in src:
        raise SystemExit(f"NOT FOUND ({label}) in {path.name}:\n---\n{old[:300]}\n---")
    src = src.replace(old, new, 1)
    path.write_text(src, encoding="utf-8")
    print(f"  \u2713 {path.relative_to(ROOT)} \u2014 {label}")


FSM = ROOT / "states/fsm.py"
KB = ROOT / "keyboards/kb.py"
TS = ROOT / "handlers/tasks.py"

# === 1. FSM-стейт ===
fsm_src = FSM.read_text(encoding="utf-8")
if "wait_new_url" not in fsm_src:
    fsm_src = fsm_src.replace(
        "class PostStates(StatesGroup):",
        "class PostStates(StatesGroup):\n    wait_new_url = State()",
        1,
    )
    FSM.write_text(fsm_src, encoding="utf-8")
    print("  \u2713 states/fsm.py \u2014 стейт wait_new_url")

# === 2. Кнопка «Ссылки» в post_card ===
patch(
    KB,
    '''    rows.append([InlineKeyboardButton(text="🗑 Удалить", callback_data=f"post_del:{post_id}")])
    rows.append([InlineKeyboardButton(text="« К задаче", callback_data=f"task:{task_id}")])''',
    '''    rows.append([InlineKeyboardButton(text="🔗 Ссылки", callback_data=f"post_links:{post_id}")])
    rows.append([InlineKeyboardButton(text="🗑 Удалить", callback_data=f"post_del:{post_id}")])
    rows.append([InlineKeyboardButton(text="« К задаче", callback_data=f"task:{task_id}")])''',
    "кнопка «Ссылки» в post_card",
)

# === 3. Хендлеры post_links / pick / wait_new_url ===
ts_src = TS.read_text(encoding="utf-8")
if "post_links" not in ts_src:
    handlers = '''


import re as _re


def _extract_links(post) -> list[str]:
    """Уникальные ссылки из html-текста и кнопок поста."""
    urls: list[str] = []
    seen = set()
    text = post["text"] or ""
    for m in _re.finditer(r'href=[\\\'"]([^\\\'"]+)[\\\'"]', text):
        u = m.group(1)
        if u not in seen:
            seen.add(u); urls.append(u)
    try:
        btns = json.loads(post["buttons"]) if post["buttons"] else []
    except Exception:
        btns = []
    for b in btns:
        u = b.get("url")
        if u and u not in seen:
            seen.add(u); urls.append(u)
    return urls


def _replace_link_everywhere(post, old_url: str, new_url: str) -> dict:
    """Возвращает {text, buttons_json} с заменённой ссылкой."""
    new_text = post["text"] or ""
    if new_text:
        # точная замена в href атрибуте (любые кавычки)
        new_text = _re.sub(
            r'href=([\\\'"])' + _re.escape(old_url) + r'\\1',
            lambda m: f'href={m.group(1)}{new_url}{m.group(1)}',
            new_text,
        )
    try:
        btns = json.loads(post["buttons"]) if post["buttons"] else []
    except Exception:
        btns = []
    for b in btns:
        if b.get("url") == old_url:
            b["url"] = new_url
    new_buttons = json.dumps(btns, ensure_ascii=False) if btns else None
    return {"text": new_text, "buttons": new_buttons}


@router.callback_query(F.data.startswith("post_links:"))
async def cb_post_links(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        return
    await state.clear()
    post_id = int(cb.data.split(":")[1])
    post = await get_db().get_post(post_id)
    if not post:
        await cb.answer("Не найдено", show_alert=True)
        return
    if post["copy_from_chat"]:
        await cb.answer(
            "В пересланных постах нельзя — контент чужой, копируется Telegram-ом 1\u2011в\u20111.",
            show_alert=True,
        )
        return
    urls = _extract_links(post)
    if not urls:
        await cb.answer("В этом посте нет ссылок", show_alert=True)
        return
    rows = []
    # отдельная callback_data для каждой ссылки — но url длинный,
    # используем индекс, сохраняем список ссылок в FSM
    await state.update_data(_link_post_id=post_id, _link_urls=urls)
    for i, u in enumerate(urls):
        short = u if len(u) <= 60 else u[:57] + "..."
        rows.append([InlineKeyboardButton(text=f"\U0001F517 {short}", callback_data=f"plink:{i}")])
    rows.append([InlineKeyboardButton(text="\u00ab К посту", callback_data=f"post:{post_id}")])
    await cb.message.edit_text(
        f"<b>\U0001F517 Ссылки в посте</b>\\n\\nВыбери, какую заменить:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("plink:"))
async def cb_plink_pick(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        return
    idx = int(cb.data.split(":")[1])
    data = await state.get_data()
    urls = data.get("_link_urls", [])
    post_id = data.get("_link_post_id")
    if idx >= len(urls) or not post_id:
        await cb.answer("Сессия устарела, открой ссылки заново", show_alert=True)
        return
    old = urls[idx]
    await state.update_data(_link_old=old)
    await state.set_state(PostStates.wait_new_url)
    await cb.message.edit_text(
        f"\u041e\u0442 \u043f\u043e\u0441\u0442\u0430: <code>{old}</code>\\n\\n"
        f"\u041f\u0440\u0438\u0448\u043b\u0438 <b>\u043d\u043e\u0432\u0443\u044e \u0441\u0441\u044b\u043b\u043a\u0443</b> (http://... или https://...). "
        f"\u0417\u0430\u043c\u0435\u043d\u044e \u0432\u0435\u0437\u0434\u0435 \u0432 \u043f\u043e\u0441\u0442\u0435."
    )
    await cb.answer()


@router.message(PostStates.wait_new_url)
async def m_plink_new(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return
    new = (message.text or "").strip()
    if not (new.startswith("http://") or new.startswith("https://") or new.startswith("tg://")):
        await message.answer("\u041d\u0443\u0436\u043d\u0430 \u043a\u043e\u0440\u0440\u0435\u043a\u0442\u043d\u0430\u044f \u0441\u0441\u044b\u043b\u043a\u0430 (http/https/tg).")
        return
    data = await state.get_data()
    post_id = data.get("_link_post_id")
    old = data.get("_link_old")
    if not post_id or not old:
        await message.answer("\u0421\u0435\u0441\u0441\u0438\u044f \u0443\u0441\u0442\u0430\u0440\u0435\u043b\u0430.")
        await state.clear()
        return
    post = await get_db().get_post(post_id)
    if not post:
        await state.clear()
        return
    new_fields = _replace_link_everywhere(post, old, new)
    await get_db().update_post(post_id, **new_fields)
    await state.clear()
    # перерисуем карточку поста
    post = await get_db().get_post(post_id)
    posts = await get_db().list_posts(post["task_id"])
    idx = next((i for i, p in enumerate(posts) if p["id"] == post_id), 0)
    await message.answer(
        f"\u2705 \u0421\u0441\u044b\u043b\u043a\u0430 \u0437\u0430\u043c\u0435\u043d\u0435\u043d\u0430:\\n"
        f"\u00ab<code>{old}</code>\u00bb\\n\u2192 \u00ab<code>{new}</code>\u00bb",
        reply_markup=post_card(post_id, post["task_id"], idx, len(posts)),
    )
'''
    # Добавим импорт PostStates в tasks.py (там его нет)
    if "from states.fsm import" in ts_src and "PostStates" not in ts_src:
        ts_src = ts_src.replace(
            "from states.fsm import TaskStates",
            "from states.fsm import TaskStates, PostStates",
            1,
        )
    elif "PostStates" not in ts_src:
        ts_src = ts_src.replace(
            "from handlers.common import is_admin",
            "from handlers.common import is_admin\nfrom states.fsm import PostStates",
            1,
        )

    # Добавим импорт InlineKeyboardButton/Markup для меню ссылок
    if "InlineKeyboardButton" not in ts_src:
        ts_src = ts_src.replace(
            "from aiogram.types import CallbackQuery, Message",
            "from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message",
            1,
        )

    # И json — если ещё не импортирован
    if "import json" not in ts_src:
        ts_src = ts_src.replace(
            "from __future__ import annotations",
            "from __future__ import annotations\n\nimport json",
            1,
        )

    ts_src += handlers
    TS.write_text(ts_src, encoding="utf-8")
    print("  \u2713 handlers/tasks.py \u2014 хендлеры редактирования ссылок")

# === 4. Метод update_post в БД (если не было) ===
DB = ROOT / "database/db.py"
db_src = DB.read_text(encoding="utf-8")
if "async def update_post" not in db_src:
    # добавим после delete_post
    anchor = "    async def delete_post(self, post_id: int) -> None:\n        await self.conn.execute(\"DELETE FROM posts WHERE id=?\", (post_id,))\n        await self.conn.commit()"
    add = anchor + '''

    async def update_post(self, post_id: int, **fields) -> None:
        if not fields:
            return
        sets = ", ".join(f"{k}=?" for k in fields)
        params = list(fields.values()) + [post_id]
        await self.conn.execute(f"UPDATE posts SET {sets} WHERE id=?", params)
        await self.conn.commit()'''
    if anchor in db_src:
        db_src = db_src.replace(anchor, add, 1)
        DB.write_text(db_src, encoding="utf-8")
        print("  \u2713 database/db.py \u2014 метод update_post")
    else:
        raise SystemExit("anchor delete_post не найден в db.py")

print("\\n\u2705 Патч применён. Перезапусти: systemctl restart autoposter")
