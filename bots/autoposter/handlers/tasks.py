"""Задачи и посты."""
from __future__ import annotations

import json

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from database import get_db
from handlers.common import is_admin
from keyboards.kb import tasks_menu, task_card, post_card
from states.fsm import TaskStates, PostStates
from utils.helpers import post_summary

router = Router()


@router.callback_query(F.data == "tasks")
async def cb_tasks(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        await cb.answer("⛔", show_alert=True)
        return
    await state.clear()
    tasks = await get_db().list_tasks()
    await cb.message.edit_text(
        f"<b>📋 Задачи</b>\n\nВсего: {len(tasks)}",
        reply_markup=tasks_menu(tasks),
    )
    await cb.answer()


@router.callback_query(F.data == "task_add")
async def cb_task_add(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        return
    await state.set_state(TaskStates.wait_name)
    await cb.message.edit_text("Пришли <b>название</b> новой задачи:")
    await cb.answer()


@router.message(TaskStates.wait_name)
async def m_task_name(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id) or not message.text:
        return
    await get_db().add_task(message.text.strip()[:64])
    await state.clear()
    tasks = await get_db().list_tasks()
    await message.answer("✅ Задача создана.", reply_markup=tasks_menu(tasks))


@router.callback_query(F.data.startswith("task:"))
async def cb_task_card(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        return
    await state.clear()
    task_id = int(cb.data.split(":")[1])
    db = get_db()
    task = await db.get_task(task_id)
    if not task:
        await cb.answer("Не найдено", show_alert=True)
        return
    posts = await db.list_posts(task_id)
    await cb.message.edit_text(
        f"<b>📋 {task['name']}</b>\n\nПостов: {len(posts)}",
        reply_markup=task_card(task_id, posts),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("task_ren:"))
async def cb_task_rename(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        return
    task_id = int(cb.data.split(":")[1])
    await state.set_state(TaskStates.wait_rename)
    await state.update_data(task_id=task_id)
    await cb.message.edit_text("Новое название задачи:")
    await cb.answer()


@router.message(TaskStates.wait_rename)
async def m_task_rename(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id) or not message.text:
        return
    data = await state.get_data()
    task_id = data["task_id"]
    await get_db().rename_task(task_id, message.text.strip()[:64])
    await state.clear()
    task = await get_db().get_task(task_id)
    posts = await get_db().list_posts(task_id)
    await message.answer(
        f"✅ Переименовано.\n\n<b>📋 {task['name']}</b>\nПостов: {len(posts)}",
        reply_markup=task_card(task_id, posts),
    )


@router.callback_query(F.data.startswith("task_del:"))
async def cb_task_del(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        return
    task_id = int(cb.data.split(":")[1])
    await get_db().delete_task(task_id)
    tasks = await get_db().list_tasks()
    await cb.message.edit_text("🗑 Задача удалена.", reply_markup=tasks_menu(tasks))
    await cb.answer()


@router.callback_query(F.data.startswith("post:"))
async def cb_post_card(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        return
    await state.clear()
    post_id = int(cb.data.split(":")[1])
    db = get_db()
    post = await db.get_post(post_id)
    if not post:
        await cb.answer("Не найдено", show_alert=True)
        return
    posts = await db.list_posts(post["task_id"])
    idx = next((i for i, p in enumerate(posts) if p["id"] == post_id), 0)
    await cb.message.edit_text(
        post_summary(post, idx + 1),
        reply_markup=post_card(post_id, post["task_id"], idx, len(posts)),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("post_up:"))
async def cb_post_up(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        return
    post_id = int(cb.data.split(":")[1])
    db = get_db()
    post = await db.get_post(post_id)
    posts = await db.list_posts(post["task_id"])
    idx = next((i for i, p in enumerate(posts) if p["id"] == post_id), 0)
    if idx > 0:
        await db.swap_post_positions(post_id, posts[idx - 1]["id"])
    await _reopen_task(cb, post["task_id"])


@router.callback_query(F.data.startswith("post_down:"))
async def cb_post_down(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        return
    post_id = int(cb.data.split(":")[1])
    db = get_db()
    post = await db.get_post(post_id)
    posts = await db.list_posts(post["task_id"])
    idx = next((i for i, p in enumerate(posts) if p["id"] == post_id), 0)
    if idx < len(posts) - 1:
        await db.swap_post_positions(post_id, posts[idx + 1]["id"])
    await _reopen_task(cb, post["task_id"])


@router.callback_query(F.data.startswith("post_del:"))
async def cb_post_del(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        return
    post_id = int(cb.data.split(":")[1])
    post = await get_db().get_post(post_id)
    task_id = post["task_id"]
    await get_db().delete_post(post_id)
    await _reopen_task(cb, task_id)


async def _reopen_task(cb: CallbackQuery, task_id: int) -> None:
    db = get_db()
    task = await db.get_task(task_id)
    posts = await db.list_posts(task_id)
    await cb.message.edit_text(
        f"<b>📋 {task['name']}</b>\n\nПостов: {len(posts)}",
        reply_markup=task_card(task_id, posts),
    )
    await cb.answer()



import re as _re


def _extract_links(post) -> list[str]:
    """Уникальные ссылки из html-текста и кнопок поста."""
    urls: list[str] = []
    seen = set()
    text = post["text"] or ""
    for m in _re.finditer(r'href=[\'"]([^\'"]+)[\'"]', text):
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
            r'href=([\'"])' + _re.escape(old_url) + r'\1',
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
            "В пересланных постах нельзя — контент чужой, копируется Telegram-ом 1‑в‑1.",
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
        rows.append([InlineKeyboardButton(text=f"🔗 {short}", callback_data=f"plink:{i}")])
    rows.append([InlineKeyboardButton(text="🆘 Запасной пул", callback_data=f"post_bk:{post_id}")])
    rows.append([InlineKeyboardButton(text="« К посту", callback_data=f"post:{post_id}")])
    await cb.message.edit_text(
        f"<b>🔗 Ссылки в посте</b>\n\nВыбери, какую заменить:",
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
        f"От поста: <code>{old}</code>\n\n"
        f"Пришли <b>новую ссылку</b> (http://... или https://...). "
        f"Заменю везде в посте."
    )
    await cb.answer()


@router.message(PostStates.wait_new_url)
async def m_plink_new(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return
    new = (message.text or "").strip()
    if not (new.startswith("http://") or new.startswith("https://") or new.startswith("tg://")):
        await message.answer("Нужна корректная ссылка (http/https/tg).")
        return
    data = await state.get_data()
    post_id = data.get("_link_post_id")
    old = data.get("_link_old")
    if not post_id or not old:
        await message.answer("Сессия устарела.")
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
        f"✅ Ссылка заменена:\n"
        f"«<code>{old}</code>»\n→ «<code>{new}</code>»",
        reply_markup=post_card(post_id, post["task_id"], idx, len(posts)),
    )



# === [patch4] смена цвета кнопок существующего поста ===
from keyboards.kb import post_color_choice as _post_color_choice


@router.callback_query(F.data.startswith("post_color:"))
async def cb_post_color(cb: CallbackQuery, state: FSMContext) -> None:
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
            "У пересланных постов кнопки берутся с оригинала — цвет менять нельзя.",
            show_alert=True,
        )
        return
    if not post["buttons"]:
        await cb.answer("В этом посте нет кнопок", show_alert=True)
        return
    await cb.message.edit_text(
        "🎨 <b>Цвет кнопок</b>\n\nВыбери цвет:",
        reply_markup=_post_color_choice(post_id),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("pcol:"))
async def cb_pcol_set(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        return
    _, post_id_s, style = cb.data.split(":")
    post_id = int(post_id_s)
    post = await get_db().get_post(post_id)
    if not post:
        await cb.answer("Не найдено", show_alert=True)
        return
    try:
        btns = json.loads(post["buttons"]) if post["buttons"] else []
    except Exception:
        btns = []
    for b in btns:
        if isinstance(b, dict) and b.get("url"):
            if style == "none":
                b.pop("style", None)
            else:
                b["style"] = style
    new_buttons = json.dumps(btns, ensure_ascii=False) if btns else None
    await get_db().update_post(post_id, buttons=new_buttons)
    label = {"success": "🟢 зелёные", "danger": "🔴 красные",
             "primary": "🔵 синие", "none": "⚪ без цвета"}.get(style, style)
    post = await get_db().get_post(post_id)
    posts = await get_db().list_posts(post["task_id"])
    idx = next((i for i, p in enumerate(posts) if p["id"] == post_id), 0)
    await cb.message.edit_text(
        f"✅ Цвет кнопок изменён: {label}.",
        reply_markup=post_card(post_id, post["task_id"], idx, len(posts)),
    )
    await cb.answer()
# === [/patch4] ===



@router.callback_query(F.data.startswith("post_bk:"))
async def cb_post_backup_pool(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        return
    await state.clear()
    post_id = int(cb.data.split(":")[1])
    post = await get_db().get_post(post_id)
    if not post:
        await cb.answer("Не найдено", show_alert=True); return
    try:
        backup = json.loads(post["backup_urls"]) if post["backup_urls"] else []
    except Exception:
        backup = []
    rows = []
    for i, u in enumerate(backup):
        short = u if len(u) <= 50 else u[:47] + "..."
        rows.append([InlineKeyboardButton(
            text=f"🆕 {short}",
            callback_data=f"post_bk_del:{post_id}:{i}",
        )])
    rows.append([InlineKeyboardButton(text="➕ Добавить запасную", callback_data=f"post_bk_add:{post_id}")])
    rows.append([InlineKeyboardButton(text="« К ссылкам", callback_data=f"post_links:{post_id}")])
    txt = (
        "<b>🆘 Запасной пул поста</b>\n\n"
        f"В пуле: {len(backup)}\n\n"
        "Перед постингом бот проверяет ссылки в посте. "
        "Если основная мертва — берёт первую живую отсюда. "
        "Если ничего живого нет — постинг ставится на стоп и приходит уведомление.\n\n"
        "Жми на ссылку чтобы удалить."
    )
    await cb.message.edit_text(txt, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await cb.answer()


@router.callback_query(F.data.startswith("post_bk_add:"))
async def cb_post_bk_add(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        return
    post_id = int(cb.data.split(":")[1])
    await state.set_state(PostStates.wait_backup_url)
    await state.update_data(_bk_post_id=post_id)
    await cb.message.edit_text(
        "Пришли запасную <b>ссылку</b> (https://t.me/... или https://...).\n\n"
        "Её бот возьмёт, если основная ссылка в посте умрёт."
    )
    await cb.answer()


@router.message(PostStates.wait_backup_url)
async def m_post_bk_add(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return
    url = (message.text or "").strip()
    if not (url.startswith("http://") or url.startswith("https://") or url.startswith("tg://")):
        await message.answer("Нужна корректная ссылка (http/https/tg).")
        return
    data = await state.get_data()
    post_id = data.get("_bk_post_id")
    if not post_id:
        await state.clear(); return
    post = await get_db().get_post(post_id)
    if not post:
        await state.clear(); return
    try:
        backup = json.loads(post["backup_urls"]) if post["backup_urls"] else []
    except Exception:
        backup = []
    if url in backup:
        await message.answer("Уже в пуле.")
        return
    backup.append(url)
    await get_db().update_post(post_id, backup_urls=json.dumps(backup, ensure_ascii=False))
    await state.clear()
    await message.answer(f"✅ Добавлена. Всего в пуле: {len(backup)}")


@router.callback_query(F.data.startswith("post_bk_del:"))
async def cb_post_bk_del(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        return
    _, post_id, idx = cb.data.split(":")
    post_id, idx = int(post_id), int(idx)
    post = await get_db().get_post(post_id)
    if not post:
        await cb.answer("Не найдено", show_alert=True); return
    try:
        backup = json.loads(post["backup_urls"]) if post["backup_urls"] else []
    except Exception:
        backup = []
    if 0 <= idx < len(backup):
        backup.pop(idx)
        await get_db().update_post(post_id, backup_urls=(json.dumps(backup, ensure_ascii=False) if backup else None))
    # рендерим заново
    await cb_post_backup_pool(cb, state)



@router.callback_query(F.data.startswith("post_edt_nd:"))
async def cb_post_edt_next_delay(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        return
    post_id = int(cb.data.split(":")[1])
    post = await get_db().get_post(post_id)
    if not post:
        await cb.answer("Не найдено", show_alert=True); return
    await state.set_state(PostStates.wait_edit_next_delay)
    await state.update_data(_edt_post_id=post_id)
    await cb.message.edit_text(
        f"⏱ <b>Время постинга</b>\n\n"
        f"Сейчас: <b>{post['next_delay']} с</b>\n\n"
        "Пришли новое значение в секундах (1+)."
    )
    await cb.answer()


@router.message(PostStates.wait_edit_next_delay)
async def m_post_edt_next_delay(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return
    try:
        v = int((message.text or "").strip())
        if v < 1:
            raise ValueError
    except ValueError:
        await message.answer("Целое число секунд (1+).")
        return
    data = await state.get_data()
    post_id = data.get("_edt_post_id")
    if not post_id:
        await state.clear(); return
    await get_db().update_post(post_id, next_delay=v)
    await state.clear()
    post = await get_db().get_post(post_id)
    if not post:
        return
    posts = await get_db().list_posts(post["task_id"])
    idx = next((i for i, p in enumerate(posts) if p["id"] == post_id), 0)
    await message.answer(
        f"✅ Время постинга: <b>{v} с</b>\n\n" + post_summary(post, idx + 1),
        reply_markup=post_card(post_id, post["task_id"], idx, len(posts)),
    )


@router.callback_query(F.data.startswith("post_edt_da:"))
async def cb_post_edt_delete_after(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        return
    post_id = int(cb.data.split(":")[1])
    post = await get_db().get_post(post_id)
    if not post:
        await cb.answer("Не найдено", show_alert=True); return
    await state.set_state(PostStates.wait_edit_delete_after)
    await state.update_data(_edt_post_id=post_id)
    cur = post["delete_after"]
    cur_txt = f"{cur} с" if cur else "не удалять"
    await cb.message.edit_text(
        f"🗑 <b>Автоудаление</b>\n\n"
        f"Сейчас: <b>{cur_txt}</b>\n\n"
        "Пришли новое значение в секундах (0 — не удалять)."
    )
    await cb.answer()


@router.message(PostStates.wait_edit_delete_after)
async def m_post_edt_delete_after(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return
    try:
        v = int((message.text or "").strip())
        if v < 0:
            raise ValueError
    except ValueError:
        await message.answer("Целое число (0 или больше).")
        return
    data = await state.get_data()
    post_id = data.get("_edt_post_id")
    if not post_id:
        await state.clear(); return
    await get_db().update_post(post_id, delete_after=v)
    await state.clear()
    post = await get_db().get_post(post_id)
    if not post:
        return
    posts = await get_db().list_posts(post["task_id"])
    idx = next((i for i, p in enumerate(posts) if p["id"] == post_id), 0)
    cur_txt = f"{v} с" if v else "не удалять"
    await message.answer(
        f"✅ Автоудаление: <b>{cur_txt}</b>\n\n" + post_summary(post, idx + 1),
        reply_markup=post_card(post_id, post["task_id"], idx, len(posts)),
    )
