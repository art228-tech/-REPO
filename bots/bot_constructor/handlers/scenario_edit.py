"""Просмотр и редактирование шагов сценария."""
from __future__ import annotations

import json
import html

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery, Message

from database import get_db
from handlers.start import is_admin
from states.fsm import StepStates
from keyboards.constructor_kb import (
    add_step_type,
    back_to,
    scenario_menu,
    step_view,
)

router = Router(name="scenario_edit")


def _describe_step(step) -> str:
    cfg = json.loads(step["config"])
    t = step["step_type"]
    if t == "roulette":
        return (
            f"🎰 <b>Рулетка</b>\n"
            f"📝 Текст: {len(cfg.get('text') or '')} симв.\n"
            f"Кнопка: <code>{html.escape(str(cfg.get('button_text') or '—'))}</code>\n"
            f"Фото: {'✅' if cfg.get('photo_file_id') else '—'}\n"
            f"Дублирование: каждые {step['duplicate_after']}с "
            f"(+{step['duplicate_increment']}), макс {step['duplicate_max']} раз"
        )
    if t == "op":
        sponsors = cfg.get("sponsors", [])
        n_check = sum(1 for s in sponsors if s.get("check"))
        return (
            f"📢 <b>Обязательная подписка</b>\n"
            f"📝 Текст: {len(cfg.get('text') or '')} симв.\n"
            f"Спонсоров: {len(sponsors)} (с проверкой: {n_check})\n"
            f"Кнопка проверки: <code>{html.escape(str(cfg.get('check_button_text') or '—'))}</code>\n"
            f"Дублирование: каждые {step['duplicate_after']}с "
            f"(+{step['duplicate_increment']}), макс {step['duplicate_max']} раз"
        )
    if t == "message":
        wm = cfg.get("wait_mode", "none")
        wm_label = {
            "timer": f"⏱ таймер {cfg.get('wait_timer', 0)} с",
            "user_message": "✉️ ждать сообщение",
            "none": "🚫 без ожидания",
        }.get(wm, wm)
        kb = cfg.get("keyboard_text")
        return (
            f"💬 <b>Сообщение</b>\n"
            f"📝 Текст: {len(cfg.get('text') or '')} симв.\n"
            f"Контент: "
            f"{'фото ' if cfg.get('photo_file_id') else ''}"
            f"{'стикер ' if cfg.get('sticker_file_id') else ''}"
            f"{'гифка ' if cfg.get('animation_file_id') else ''}"
            f"{'видео ' if cfg.get('video_file_id') else ''}"
            f"{'копия-поста ' if cfg.get('copy_from') else ''}"
            f"\nКнопок: {len(cfg.get('buttons', []))}\n"
            f"Ожидание: {wm_label}\n"
            f"Кнопка клавиатуры: {kb or '—'}\n"
            f"Дублирование: каждые {step['duplicate_after']}с "
            f"(+{step['duplicate_increment']}), макс {step['duplicate_max']} раз"
        )
    return "?"


@router.callback_query(F.data.startswith("scn:"))
async def cb_scenario(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        await cb.answer("⛔", show_alert=True)
        return
    await state.clear()
    bot_id = int(cb.data.split(":")[1])
    steps = await get_db().list_steps(bot_id)
    text = f"<b>📜 Сценарий</b>\nШагов: {len(steps)}"
    if not steps:
        text += "\n\nДобавь первый шаг 👇"
    await cb.message.edit_text(text, reply_markup=scenario_menu(bot_id, steps))
    await cb.answer()


@router.callback_query(F.data.startswith("addstep:"))
async def cb_addstep(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        await cb.answer("⛔", show_alert=True)
        return
    await state.clear()
    bot_id = int(cb.data.split(":")[1])
    await cb.message.edit_text(
        "<b>➕ Выбери тип шага</b>\n\n"
        "🎰 Рулетка — текст + кнопка-вебка с красивой рулеткой.\n"
        "📢 ОП — каналы-спонсоры с проверкой подписки.\n"
        "💬 Сообщение — текст/фото/гифка/стикер + кнопки + ожидание.",
        reply_markup=add_step_type(bot_id),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("step:"))
async def cb_step_view(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        await cb.answer("⛔", show_alert=True)
        return
    await state.clear()
    step_id = int(cb.data.split(":")[1])
    step = await get_db().get_step(step_id)
    if not step:
        await cb.answer("Шаг не найден", show_alert=True)
        return
    text = f"<b>Шаг {step['step_order']+1}</b>\n\n" + _describe_step(step)
    await cb.message.edit_text(text, reply_markup=step_view(step_id, step["bot_id"], step["step_type"]))
    await cb.answer()


@router.callback_query(F.data.startswith("step_up:"))
async def cb_step_up(cb: CallbackQuery) -> None:
    step_id = int(cb.data.split(":")[1])
    await get_db().move_step(step_id, -1)
    step = await get_db().get_step(step_id)
    if not step:
        await cb.answer("Не найдено", show_alert=True)
        return
    text = f"<b>Шаг {step['step_order']+1}</b>\n\n" + _describe_step(step)
    await cb.message.edit_text(text, reply_markup=step_view(step_id, step["bot_id"], step["step_type"]))
    await cb.answer("⬆️")


@router.callback_query(F.data.startswith("step_dn:"))
async def cb_step_dn(cb: CallbackQuery) -> None:
    step_id = int(cb.data.split(":")[1])
    await get_db().move_step(step_id, +1)
    step = await get_db().get_step(step_id)
    if not step:
        await cb.answer("Не найдено", show_alert=True)
        return
    text = f"<b>Шаг {step['step_order']+1}</b>\n\n" + _describe_step(step)
    await cb.message.edit_text(text, reply_markup=step_view(step_id, step["bot_id"], step["step_type"]))
    await cb.answer("⬇️")


@router.callback_query(F.data.startswith("step_del:"))
async def cb_step_del(cb: CallbackQuery) -> None:
    step_id = int(cb.data.split(":")[1])
    step = await get_db().get_step(step_id)
    if not step:
        await cb.answer("Не найдено", show_alert=True)
        return
    bot_id = step["bot_id"]
    await get_db().delete_step(step_id)
    steps = await get_db().list_steps(bot_id)
    await cb.message.edit_text(
        f"🗑 Шаг удалён.\n<b>Шагов:</b> {len(steps)}",
        reply_markup=scenario_menu(bot_id, steps),
    )
    await cb.answer("Удалено")



@router.callback_query(F.data.startswith("step_txt:"))
async def cb_step_text(cb: CallbackQuery, state: FSMContext) -> None:
    """Показывает сырой текст шага отдельным сообщением, чтобы избежать
    PEER_FLOOD при edit_text карточки шага с плотным контентом."""
    if not is_admin(cb.from_user.id):
        await cb.answer("⛔", show_alert=True)
        return
    step_id = int(cb.data.split(":")[1])
    step = await get_db().get_step(step_id)
    if not step:
        await cb.answer("Шаг не найден", show_alert=True)
        return
    cfg = json.loads(step["config"])
    text = cfg.get("text") or ""
    if not text:
        await cb.answer("У шага нет текста", show_alert=True)
        return
    try:
        await cb.message.answer(
            text,
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )
    except Exception as e:
        await cb.answer(f"Не удалось показать: {e}", show_alert=True)
        return
    await cb.answer()



import re as _re_links


def _extract_step_links(cfg: dict) -> list[str]:
    """Уникальные ссылки из html-текста и из кнопок шага."""
    urls: list[str] = []
    seen = set()
    text = cfg.get("text") or ""
    for m in _re_links.finditer(r'href=[\'"]([^\'"]+)[\'"]', text):
        u = m.group(1)
        if u not in seen:
            seen.add(u); urls.append(u)
    for b in (cfg.get("buttons") or []):
        u = b.get("url")
        if u and u not in seen:
            seen.add(u); urls.append(u)
    return urls


def _replace_step_link(cfg: dict, old_url: str, new_url: str) -> dict:
    """Возвращает обновлённый cfg с заменой ссылки везде."""
    cfg = dict(cfg)
    text = cfg.get("text") or ""
    if text:
        cfg["text"] = _re_links.sub(
            r'href=([\'"])' + _re_links.escape(old_url) + r'\1',
            lambda m: f'href={m.group(1)}{new_url}{m.group(1)}',
            text,
        )
    btns = cfg.get("buttons") or []
    new_btns = []
    for b in btns:
        if isinstance(b, dict):
            b = dict(b)
            if b.get("url") == old_url:
                b["url"] = new_url
        new_btns.append(b)
    cfg["buttons"] = new_btns
    return cfg


@router.callback_query(F.data.startswith("step_links:"))
async def cb_step_links(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        await cb.answer("⛔", show_alert=True)
        return
    await state.clear()
    step_id = int(cb.data.split(":")[1])
    step = await get_db().get_step(step_id)
    if not step:
        await cb.answer("Шаг не найден", show_alert=True)
        return
    cfg = json.loads(step["config"])
    if cfg.get("copy_from"):
        await cb.answer(
            "В скопированных постах нельзя — контент чужой, копируется Telegram-ом 1‑в‑1.",
            show_alert=True,
        )
        return
    urls = _extract_step_links(cfg)
    if not urls:
        await cb.answer("В этом шаге нет ссылок", show_alert=True)
        return
    await state.update_data(_link_step_id=step_id, _link_urls=urls)
    rows = []
    for i, u in enumerate(urls):
        short = u if len(u) <= 60 else u[:57] + "..."
        rows.append([InlineKeyboardButton(text=f"🔗 {short}", callback_data=f"plink:{i}")])
    rows.append([InlineKeyboardButton(text="« К шагу", callback_data=f"step:{step_id}")])
    await cb.message.edit_text(
        "<b>🔗 Ссылки в шаге</b>\n\nВыбери, какую заменить:",
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
    step_id = data.get("_link_step_id")
    if idx >= len(urls) or not step_id:
        await cb.answer("Сессия устарела, открой ссылки заново", show_alert=True)
        return
    url = urls[idx]
    step = await get_db().get_step(step_id)
    cfg = json.loads(step["config"]) if step else {}
    backups = (cfg.get("link_backups") or {}).get(url, [])
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Заменить ссылку", callback_data=f"plrep:{idx}")],
        [InlineKeyboardButton(text=f"🛟 Запасные ссылки ({len(backups)})", callback_data=f"plbk:{idx}")],
        [InlineKeyboardButton(text="« Назад", callback_data=f"step_links:{step_id}")],
    ])
    await cb.message.edit_text(
        f"🔗 <code>{url}</code>\n\n"
        "• <b>Заменить</b> — вручную поменять ссылку везде в шаге.\n"
        "• <b>Запасные</b> — если бот по этой ссылке удалят, бот сам подставит "
        "рабочую запасную и пришлёт уведомление.",
        reply_markup=kb,
    )
    await cb.answer()


@router.callback_query(F.data.startswith("plrep:"))
async def cb_plink_replace(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        return
    idx = int(cb.data.split(":")[1])
    data = await state.get_data()
    urls = data.get("_link_urls", [])
    if idx >= len(urls):
        await cb.answer("Сессия устарела", show_alert=True)
        return
    await state.update_data(_link_old=urls[idx])
    await state.set_state(StepStates.step_link_new_url)
    await cb.message.edit_text(
        f"Старая ссылка: <code>{urls[idx]}</code>\n\n"
        "Пришли <b>новую ссылку</b> (http://... / https://... / tg://...). "
        "Заменю везде в этом шаге."
    )
    await cb.answer()


def _backups_menu(idx: int, url: str, backups: list, step_id: int) -> InlineKeyboardMarkup:
    rows = []
    for j, b in enumerate(backups):
        short = b if len(b) <= 45 else b[:42] + "..."
        rows.append([
            InlineKeyboardButton(text=f"{j+1}. {short}", callback_data="noop"),
            InlineKeyboardButton(text="🗑", callback_data=f"plbkd:{idx}:{j}"),
        ])
    rows.append([InlineKeyboardButton(text="➕ Добавить запасную", callback_data=f"plbka:{idx}")])
    rows.append([InlineKeyboardButton(text="« Назад", callback_data=f"plink:{idx}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data.startswith("plbk:"))
async def cb_plink_backups(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        return
    idx = int(cb.data.split(":")[1])
    data = await state.get_data()
    urls = data.get("_link_urls", [])
    step_id = data.get("_link_step_id")
    if idx >= len(urls) or not step_id:
        await cb.answer("Сессия устарела", show_alert=True)
        return
    url = urls[idx]
    step = await get_db().get_step(step_id)
    cfg = json.loads(step["config"]) if step else {}
    backups = (cfg.get("link_backups") or {}).get(url, [])
    await cb.message.edit_text(
        f"🛟 <b>Запасные для</b>\n<code>{url}</code>\n\n"
        + ("Список запасных (по порядку). Если основная ссылка умрёт — "
           "бот подставит первую рабочую запасную.\n"
           if backups else "Пока запасных нет. Добавь хотя бы одну.\n"),
        reply_markup=_backups_menu(idx, url, backups, step_id),
    )
    await cb.answer()


@router.callback_query(F.data == "noop")
async def cb_noop(cb: CallbackQuery) -> None:
    await cb.answer()


@router.callback_query(F.data.startswith("plbka:"))
async def cb_plink_backup_add(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        return
    idx = int(cb.data.split(":")[1])
    data = await state.get_data()
    urls = data.get("_link_urls", [])
    if idx >= len(urls):
        await cb.answer("Сессия устарела", show_alert=True)
        return
    await state.update_data(_bk_idx=idx, _bk_url=urls[idx])
    await state.set_state(StepStates.step_backup_url)
    await cb.message.edit_text(
        "Пришли <b>запасную ссылку</b> (http://... / https://... / tg://...).\n"
        "Лучше всего — ссылку на другого бота-дубль."
    )
    await cb.answer()


@router.message(StepStates.step_backup_url)
async def m_plink_backup_add(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return
    new = (message.text or "").strip()
    if not (new.startswith("http://") or new.startswith("https://") or new.startswith("tg://")):
        await message.answer("Нужна корректная ссылка (http/https/tg).")
        return
    data = await state.get_data()
    step_id = data.get("_link_step_id")
    url = data.get("_bk_url")
    idx = data.get("_bk_idx", 0)
    step = await get_db().get_step(step_id) if step_id else None
    if not step or not url:
        await message.answer("Сессия устарела.")
        await state.clear()
        return
    cfg = json.loads(step["config"])
    lb = cfg.get("link_backups") or {}
    arr = lb.get(url, [])
    if new not in arr and new != url:
        arr.append(new)
    lb[url] = arr
    cfg["link_backups"] = lb
    await get_db().update_step(step_id, config=json.dumps(cfg, ensure_ascii=False))
    await state.set_state(None)
    await message.answer(
        f"✅ Запасная добавлена ({len(arr)} шт.) для\n<code>{url}</code>",
        reply_markup=_backups_menu(idx, url, arr, step_id),
    )


@router.callback_query(F.data.startswith("plbkd:"))
async def cb_plink_backup_del(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        return
    _, sidx, sj = cb.data.split(":")
    idx, j = int(sidx), int(sj)
    data = await state.get_data()
    urls = data.get("_link_urls", [])
    step_id = data.get("_link_step_id")
    if idx >= len(urls) or not step_id:
        await cb.answer("Сессия устарела", show_alert=True)
        return
    url = urls[idx]
    step = await get_db().get_step(step_id)
    cfg = json.loads(step["config"]) if step else {}
    lb = cfg.get("link_backups") or {}
    arr = lb.get(url, [])
    if 0 <= j < len(arr):
        arr.pop(j)
    if arr:
        lb[url] = arr
    else:
        lb.pop(url, None)
    cfg["link_backups"] = lb
    await get_db().update_step(step_id, config=json.dumps(cfg, ensure_ascii=False))
    await cb.message.edit_text(
        f"🛟 <b>Запасные для</b>\n<code>{url}</code>\n\n"
        + ("Список запасных (по порядку).\n" if arr else "Запасных нет.\n"),
        reply_markup=_backups_menu(idx, url, arr, step_id),
    )
    await cb.answer("Удалено")


@router.message(StepStates.step_link_new_url)
async def m_plink_new(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return
    new = (message.text or "").strip()
    if not (new.startswith("http://") or new.startswith("https://") or new.startswith("tg://")):
        await message.answer("Нужна корректная ссылка (http/https/tg).")
        return
    data = await state.get_data()
    step_id = data.get("_link_step_id")
    old = data.get("_link_old")
    if not step_id or not old:
        await message.answer("Сессия устарела.")
        await state.clear()
        return
    step = await get_db().get_step(step_id)
    if not step:
        await state.clear()
        return
    cfg = json.loads(step["config"])
    new_cfg = _replace_step_link(cfg, old, new)
    await get_db().update_step(step_id, config=json.dumps(new_cfg, ensure_ascii=False))
    await state.clear()
    await message.answer(
        f"✅ Ссылка заменена в шаге:\n"
        f"«<code>{old}</code>»\n→ «<code>{new}</code>»"
    )
