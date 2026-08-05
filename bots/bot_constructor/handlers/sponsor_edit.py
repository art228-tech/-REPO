"""Управление спонсорами шага ОП: добавить/удалить/изменить порядок/редактировать."""
from __future__ import annotations

import json
import logging
from typing import Any

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from database import get_db
from handlers.start import is_admin
from utils.helpers import (
    STYLE_LABELS,
    extract_first_custom_emoji_id,
    strip_custom_emoji,
)
from utils.sponsor_check import check_sponsor_access

log = logging.getLogger("sponsor_edit")
router = Router()


# ===== FSM-стейты для редактирования полей =====
class SponsorEdit(StatesGroup):
    wait_chan_id = State()
    wait_link = State()
    wait_title = State()
    wait_btn_text = State()
    wait_btn_color = State()
    wait_request_mode = State()


# ===== Утилиты =====
async def _load_step(step_id: int):
    db = get_db()
    step = await db.get_step(step_id)
    if not step or step["step_type"] != "op":
        return None, None
    cfg = json.loads(step["config"])
    cfg.setdefault("sponsors", [])
    return step, cfg


async def _save_step_cfg(step_id: int, cfg: dict) -> None:
    db = get_db()
    await db.conn.execute(
        "UPDATE steps SET config = ? WHERE id = ?",
        (json.dumps(cfg, ensure_ascii=False), step_id),
    )
    await db.conn.commit()


def _sp_label(sp: dict) -> str:
    name = sp.get("title") or sp.get("button_text") or str(sp.get("channel_id") or "—")
    mark = "✋" if sp.get("request_mode") else ("✅" if sp.get("check") else "💤")
    return f"{mark} {name[:30]}"


def _list_kb(step_id: int, sponsors: list[dict]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for idx, sp in enumerate(sponsors):
        rows.append([
            InlineKeyboardButton(text=_sp_label(sp), callback_data=f"spo:{step_id}:{idx}"),
            InlineKeyboardButton(text="⬆️", callback_data=f"spu:{step_id}:{idx}"),
            InlineKeyboardButton(text="⬇️", callback_data=f"spd:{step_id}:{idx}"),
        ])
    rows.append([InlineKeyboardButton(text="➕ Добавить спонсора", callback_data=f"spnew:{step_id}")])
    rows.append([InlineKeyboardButton(text="« К шагу", callback_data=f"step:{step_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _one_kb(step_id: int, idx: int, sp: dict) -> InlineKeyboardMarkup:
    mode = "✋ По заявкам" if sp.get("request_mode") else "📺 Обычный"
    check_lbl = "✅ Проверять подписку" if sp.get("check") else "💤 Только показывать"
    rows = [
        [InlineKeyboardButton(text="✏️ Название", callback_data=f"spe:{step_id}:{idx}:title")],
        [InlineKeyboardButton(text="✏️ Текст кнопки", callback_data=f"spe:{step_id}:{idx}:btext")],
        [InlineKeyboardButton(text="🎨 Цвет кнопки", callback_data=f"spe:{step_id}:{idx}:bcolor")],
        [InlineKeyboardButton(text="🔗 Ссылка", callback_data=f"spe:{step_id}:{idx}:link")],
        [InlineKeyboardButton(text=f"{check_lbl}", callback_data=f"spe:{step_id}:{idx}:check")],
    ]
    # Поля проверки нужны только когда проверка включена
    if sp.get("check"):
        rows.append([InlineKeyboardButton(text="📡 chat_id", callback_data=f"spe:{step_id}:{idx}:chan")])
        rows.append([InlineKeyboardButton(text=f"⚙️ Режим: {mode}", callback_data=f"spe:{step_id}:{idx}:mode")])
        rows.append([InlineKeyboardButton(text="🧪 Тест доступа", callback_data=f"sptest:{step_id}:{idx}")])
    rows.append([InlineKeyboardButton(text="🗑 Удалить", callback_data=f"sprm:{step_id}:{idx}")])
    rows.append([InlineKeyboardButton(text="« К списку", callback_data=f"spons:{step_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _format_sp(sp: dict) -> str:
    return (
        f"<b>Спонсор</b>\n\n"
        f"Название: <code>{sp.get('title') or '—'}</code>\n"
        f"Текст кнопки: <code>{sp.get('button_text') or '—'}</code>\n"
        f"Цвет: {STYLE_LABELS.get(sp.get('button_color', 'default'), '—')}\n"
        f"Ссылка: <code>{sp.get('link') or '—'}</code>\n"
        f"chat_id: <code>{sp.get('channel_id') or '—'}</code>\n"
        f"Проверка подписки: {'✅' if sp.get('check') else '🚫'}\n"
        f"Режим: {'✋ по заявкам' if sp.get('request_mode') else '📺 обычный'}"
    )


# ===== Список спонсоров =====
@router.callback_query(F.data.startswith("spons:"))
async def cb_sponsors_list(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        await cb.answer("⛔", show_alert=True)
        return
    step_id = int(cb.data.split(":")[1])
    step, cfg = await _load_step(step_id)
    if not step:
        await cb.answer("Шаг не найден", show_alert=True)
        return
    sponsors = cfg["sponsors"]
    text = f"<b>👥 Спонсоры шага</b>\n\nВсего: {len(sponsors)}\n\n✅ — с проверкой, 💤 — показывается без проверки, ✋ — по заявкам"
    await cb.message.edit_text(text, reply_markup=_list_kb(step_id, sponsors))
    await cb.answer()


# ===== Добавить нового спонсора в существующий шаг =====
@router.callback_query(F.data.startswith("spnew:"))
async def cb_sponsor_new(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        await cb.answer("⛔", show_alert=True)
        return
    step_id = int(cb.data.split(":")[1])
    step, cfg = await _load_step(step_id)
    if not step:
        await cb.answer("Шаг не найден", show_alert=True)
        return
    sp = {
        "title": "Новый спонсор",
        "button_text": "Подписаться",
        "button_color": "default",
        "link": "",
        "channel_id": 0,
        "check": True,
        "request_mode": False,
    }
    cfg["sponsors"].append(sp)
    idx = len(cfg["sponsors"]) - 1
    await _save_step_cfg(step_id, cfg)
    await cb.message.edit_text(
        "✅ Спонсор добавлен. Заполни поля (как минимум «🔗 Ссылка», а для "
        "проверки подписки — «📡 chat_id»):\n\n" + _format_sp(sp),
        reply_markup=_one_kb(step_id, idx, sp),
    )
    await cb.answer()


# ===== Открыть карточку одного спонсора =====
@router.callback_query(F.data.startswith("spo:"))
async def cb_sponsor_open(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        return
    _, step_id_s, idx_s = cb.data.split(":")
    step_id, idx = int(step_id_s), int(idx_s)
    step, cfg = await _load_step(step_id)
    if not step or idx >= len(cfg["sponsors"]):
        await cb.answer("Не найдено", show_alert=True)
        return
    sp = cfg["sponsors"][idx]
    await cb.message.edit_text(_format_sp(sp), reply_markup=_one_kb(step_id, idx, sp))
    await cb.answer()


# ===== Перемещение в списке =====
@router.callback_query(F.data.regexp(r"^sp[ud]:\d+:\d+$"))
async def cb_sponsor_move(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        return
    parts = cb.data.split(":")
    direction = parts[0]  # spu или spd
    step_id, idx = int(parts[1]), int(parts[2])
    step, cfg = await _load_step(step_id)
    if not step:
        await cb.answer("Не найдено", show_alert=True)
        return
    sponsors = cfg["sponsors"]
    new_idx = idx - 1 if direction == "spu" else idx + 1
    if not (0 <= new_idx < len(sponsors)):
        await cb.answer("Дальше некуда")
        return
    sponsors[idx], sponsors[new_idx] = sponsors[new_idx], sponsors[idx]
    await _save_step_cfg(step_id, cfg)
    await cb.message.edit_reply_markup(reply_markup=_list_kb(step_id, sponsors))
    await cb.answer("Переставлено")


# ===== Удаление (с подтверждением) =====
@router.callback_query(F.data.startswith("sprm:"))
async def cb_sponsor_remove(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        return
    _, step_id_s, idx_s = cb.data.split(":")
    step_id, idx = int(step_id_s), int(idx_s)
    step, cfg = await _load_step(step_id)
    if not step or idx >= len(cfg["sponsors"]):
        await cb.answer("Не найдено", show_alert=True)
        return
    sp = cfg["sponsors"][idx]
    name = sp.get("title") or sp.get("button_text") or str(sp.get("channel_id"))
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"sprmy:{step_id}:{idx}")],
        [InlineKeyboardButton(text="« Отмена", callback_data=f"spo:{step_id}:{idx}")],
    ])
    await cb.message.edit_text(
        f"❓ Точно удалить спонсора <b>{name}</b>?\n\nДанные стерутся безвозвратно.",
        reply_markup=kb,
    )
    await cb.answer()


@router.callback_query(F.data.startswith("sprmy:"))
async def cb_sponsor_remove_yes(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        return
    _, step_id_s, idx_s = cb.data.split(":")
    step_id, idx = int(step_id_s), int(idx_s)
    step, cfg = await _load_step(step_id)
    if not step or idx >= len(cfg["sponsors"]):
        await cb.answer("Не найдено", show_alert=True)
        return
    removed = cfg["sponsors"].pop(idx)
    await _save_step_cfg(step_id, cfg)
    await cb.message.edit_text(
        f"🗑 Спонсор удалён.",
        reply_markup=_list_kb(step_id, cfg["sponsors"]),
    )
    await cb.answer()


# ===== Тест доступа =====
@router.callback_query(F.data.startswith("sptest:"))
async def cb_sponsor_test(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        return
    _, step_id_s, idx_s = cb.data.split(":")
    step_id, idx = int(step_id_s), int(idx_s)
    step, cfg = await _load_step(step_id)
    if not step or idx >= len(cfg["sponsors"]):
        await cb.answer("Не найдено", show_alert=True)
        return
    sp = cfg["sponsors"][idx]
    cid = sp.get("channel_id")
    if not cid:
        await cb.answer("Нет chat_id у этого спонсора", show_alert=True)
        return

    from bots.manager import get_manager
    bot_instance = get_manager().get_bot_instance(step["bot_id"])
    if bot_instance is None:
        await cb.answer("Приветка не активна — сначала запусти её", show_alert=True)
        return

    res = await check_sponsor_access(
        bot_instance, int(cid),
        require_invite_users=bool(sp.get("request_mode")),
    )
    if res["ok"]:
        status = res["details"].get("status", "?")
        msg = f"✅ Всё ок\n\nСтатус: <b>{status}</b>"
        if sp.get("request_mode"):
            msg += f"\ncan_invite_users: <b>{res['details'].get('can_invite_users')}</b>"
    else:
        msg = f"❌ Проблема\n\n{res['reason']}"
    await cb.answer(msg, show_alert=True)


# ===== Редактирование полей =====
@router.callback_query(F.data.startswith("spe:"))
async def cb_sponsor_edit(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        return
    _, step_id_s, idx_s, field = cb.data.split(":")
    step_id, idx = int(step_id_s), int(idx_s)
    step, cfg = await _load_step(step_id)
    if not step or idx >= len(cfg["sponsors"]):
        await cb.answer("Не найдено", show_alert=True)
        return
    await state.set_data({"step_id": step_id, "idx": idx, "field": field})

    if field == "title":
        await state.set_state(SponsorEdit.wait_title)
        await cb.message.edit_text("Пришли новое <b>название</b> спонсора:")
    elif field == "btext":
        await state.set_state(SponsorEdit.wait_btn_text)
        await cb.message.edit_text("Пришли новый <b>текст кнопки</b> (можно с премиум-стикером):")
    elif field == "bcolor":
        await state.set_state(SponsorEdit.wait_btn_color)
        rows = [[InlineKeyboardButton(text=label, callback_data=f"spclr:{code}")]
                for code, label in STYLE_LABELS.items()]
        rows.append([InlineKeyboardButton(text="« Отмена", callback_data=f"spo:{step_id}:{idx}")])
        await cb.message.edit_text("Выбери <b>цвет кнопки</b>:",
                                   reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    elif field == "link":
        await state.set_state(SponsorEdit.wait_link)
        await cb.message.edit_text("Пришли новую <b>ссылку</b> (https://t.me/...):")
    elif field == "chan":
        await state.set_state(SponsorEdit.wait_chan_id)
        await cb.message.edit_text("Пришли новый <b>chat_id</b> (отрицательное число):")
    elif field == "mode":
        sp = cfg["sponsors"][idx]
        sp["request_mode"] = not bool(sp.get("request_mode"))
        await _save_step_cfg(step_id, cfg)
        await cb.message.edit_text(_format_sp(sp), reply_markup=_one_kb(step_id, idx, sp))
        await cb.answer("Режим переключён")
        return
    elif field == "check":
        sp = cfg["sponsors"][idx]
        sp["check"] = not bool(sp.get("check"))
        await _save_step_cfg(step_id, cfg)
        await cb.message.edit_text(_format_sp(sp), reply_markup=_one_kb(step_id, idx, sp))
        await cb.answer("Проверка: " + ("включена" if sp["check"] else "выключена"))
        return
    await cb.answer()


# ===== Приём значений =====
async def _apply_change(state: FSMContext, value_setter) -> tuple[int, int, dict]:
    data = await state.get_data()
    step_id, idx = data["step_id"], data["idx"]
    step, cfg = await _load_step(step_id)
    if not step or idx >= len(cfg["sponsors"]):
        return step_id, idx, {}
    sp = cfg["sponsors"][idx]
    value_setter(sp)
    await _save_step_cfg(step_id, cfg)
    await state.clear()
    return step_id, idx, sp


@router.message(SponsorEdit.wait_title)
async def m_title(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.answer("Нужен текст.")
        return
    step_id, idx, sp = await _apply_change(state, lambda s: s.update({"title": message.text.strip()}))
    if sp:
        await message.answer(_format_sp(sp), reply_markup=_one_kb(step_id, idx, sp))


@router.message(SponsorEdit.wait_btn_text)
async def m_btext(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.answer("Нужен текст.")
        return
    html = message.html_text or message.text
    txt = strip_custom_emoji(html) or message.text.strip()
    cust = extract_first_custom_emoji_id(html)
    def setter(s):
        s["button_text"] = txt
        if cust:
            s["custom_emoji_id"] = cust
        else:
            s.pop("custom_emoji_id", None)
    step_id, idx, sp = await _apply_change(state, setter)
    if sp:
        await message.answer(_format_sp(sp), reply_markup=_one_kb(step_id, idx, sp))


@router.callback_query(SponsorEdit.wait_btn_color, F.data.startswith("spclr:"))
async def cb_bcolor(cb: CallbackQuery, state: FSMContext) -> None:
    color = cb.data.split(":", 1)[1]
    step_id, idx, sp = await _apply_change(state, lambda s: s.update({"button_color": color}))
    if sp:
        await cb.message.edit_text(_format_sp(sp), reply_markup=_one_kb(step_id, idx, sp))
    await cb.answer("Цвет сохранён")


@router.message(SponsorEdit.wait_link)
async def m_link(message: Message, state: FSMContext) -> None:
    link = (message.text or "").strip()
    if not (link.startswith("http://") or link.startswith("https://") or link.startswith("tg://")):
        await message.answer("Нужен URL вида https://t.me/...")
        return
    step_id, idx, sp = await _apply_change(state, lambda s: s.update({"link": link}))
    if sp:
        await message.answer(_format_sp(sp), reply_markup=_one_kb(step_id, idx, sp))


@router.message(SponsorEdit.wait_chan_id)
async def m_chan(message: Message, state: FSMContext) -> None:
    try:
        v = int((message.text or "").strip())
    except ValueError:
        await message.answer("Нужно целое число.")
        return
    # Сразу проверяем доступ
    data = await state.get_data()
    step_id, idx = data["step_id"], data["idx"]
    step, cfg = await _load_step(step_id)
    if not step or idx >= len(cfg["sponsors"]):
        await state.clear()
        return
    sp = cfg["sponsors"][idx]

    from bots.manager import get_manager
    bot_instance = get_manager().get_bot_instance(step["bot_id"])
    if bot_instance is not None:
        res = await check_sponsor_access(
            bot_instance, v, require_invite_users=bool(sp.get("request_mode"))
        )
        if not res["ok"]:
            await message.answer(
                f"⚠️ Не сохраняю — нет доступа.\n\n{res['reason']}\n\n"
                "Исправь права и пришли chat_id ещё раз."
            )
            return

    sp["channel_id"] = v
    await _save_step_cfg(step_id, cfg)
    await state.clear()
    await message.answer("✅ Сохранено.\n\n" + _format_sp(sp),
                         reply_markup=_one_kb(step_id, idx, sp))
