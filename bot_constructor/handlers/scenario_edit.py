"""Просмотр и редактирование шагов сценария."""
from __future__ import annotations

import json

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from database import get_db
from handlers.start import is_admin
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
            f"Текст: {(cfg.get('text') or '—')[:200]}\n"
            f"Кнопка: <code>{cfg.get('button_text') or '—'}</code>\n"
            f"Фото: {'✅' if cfg.get('photo_file_id') else '—'}\n"
            f"Дублирование: каждые {step['duplicate_after']}с "
            f"(+{step['duplicate_increment']}), макс {step['duplicate_max']} раз"
        )
    if t == "op":
        sponsors = cfg.get("sponsors", [])
        n_check = sum(1 for s in sponsors if s.get("check"))
        return (
            f"📢 <b>Обязательная подписка</b>\n"
            f"Текст: {(cfg.get('text') or '—')[:200]}\n"
            f"Спонсоров: {len(sponsors)} (с проверкой: {n_check})\n"
            f"Кнопка проверки: <code>{cfg.get('check_button_text') or '—'}</code>\n"
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
            f"Текст: {(cfg.get('text') or '—')[:200]}\n"
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
    await cb.message.edit_text(text, reply_markup=step_view(step_id, step["bot_id"]))
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
    await cb.message.edit_text(text, reply_markup=step_view(step_id, step["bot_id"]))
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
    await cb.message.edit_text(text, reply_markup=step_view(step_id, step["bot_id"]))
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
