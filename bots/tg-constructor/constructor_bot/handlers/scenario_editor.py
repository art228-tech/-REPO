"""
Full scenario editor: add/edit/reorder steps, set messages, OP sponsors, delays.
"""
import os
import json
from aiogram import Router, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from shared.db import db
from shared.models import ScenarioStep, Sponsor, WelcomeBot
from constructor_bot.keyboards.menus import (
    scenario_menu_kb, add_step_type_kb, step_menu_kb,
    sponsors_kb, cancel_kb, back_kb
)

router = Router()
MEDIA_DIR = os.getenv("MEDIA_DIR", "/app/media")


class ScenarioFSM(StatesGroup):
    # Step message capture
    waiting_message = State()
    # Delay after step
    waiting_delay = State()
    # Waiting text (shown during delay)
    waiting_wait_text = State()
    # Sponsor fields
    waiting_sponsor_title = State()
    waiting_sponsor_url = State()
    waiting_sponsor_channel_id = State()


# ─── Scenario overview ───────────────────────────────────────────

@router.callback_query(F.data.startswith("scenario:"))
async def cb_scenario(callback: CallbackQuery):
    bot_id = int(callback.data.split(":")[1])
    async with db() as session:
        result = await session.execute(
            select(ScenarioStep)
            .where(ScenarioStep.bot_id == bot_id)
            .order_by(ScenarioStep.position)
        )
        steps = result.scalars().all()

    text = f"📋 <b>Сценарий бота</b>\n\nШагов: {len(steps)}"
    if not steps:
        text += "\n\n<i>Сценарий пуст. Добавьте первый шаг.</i>"
    await callback.message.edit_text(text, reply_markup=scenario_menu_kb(bot_id, steps))
    await callback.answer()


# ─── Add step ────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("add_step:"))
async def cb_add_step(callback: CallbackQuery):
    bot_id = int(callback.data.split(":")[1])
    await callback.message.edit_text(
        "➕ <b>Добавить шаг</b>\n\nВыберите тип шага:",
        reply_markup=add_step_type_kb(bot_id)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("new_step:"))
async def cb_new_step(callback: CallbackQuery, state: FSMContext):
    _, step_type, bot_id_str = callback.data.split(":")
    bot_id = int(bot_id_str)

    # Determine next position
    async with db() as session:
        result = await session.execute(
            select(ScenarioStep).where(ScenarioStep.bot_id == bot_id).order_by(ScenarioStep.position.desc())
        )
        last = result.scalars().first()
        position = (last.position + 1) if last else 0

        new_step = ScenarioStep(bot_id=bot_id, step_type=step_type, position=position)
        session.add(new_step)
        await session.flush()
        step_id = new_step.id

    await state.update_data(step_id=step_id, bot_id=bot_id)
    await state.set_state(ScenarioFSM.waiting_message)

    await callback.message.edit_text(
        "✉️ <b>Отправьте сообщение для этого шага</b>\n\n"
        "Перешлите любое сообщение (текст, фото, стикер, видео, документ) — "
        "бот запомнит его и будет пересылать пользователям.\n\n"
        "Если хотите <b>пропустить</b> сообщение — нажмите кнопку ниже.",
        reply_markup=cancel_kb(f"scenario:{bot_id}")
    )
    await callback.answer()


@router.callback_query(F.data.startswith("edit_step_msg:"))
async def cb_edit_step_msg(callback: CallbackQuery, state: FSMContext):
    step_id = int(callback.data.split(":")[1])
    async with db() as session:
        step = await session.get(ScenarioStep, step_id)

    await state.update_data(step_id=step_id, bot_id=step.bot_id)
    await state.set_state(ScenarioFSM.waiting_message)
    await callback.message.edit_text(
        "✉️ Перешлите новое сообщение для этого шага (или напишите текст).\n"
        "Нажмите «Пропустить», чтобы убрать сообщение.",
        reply_markup=cancel_kb(f"step_menu:{step_id}")
    )
    await callback.answer()


async def _serialize_message(msg: Message) -> dict:
    """Extract forwarded/original message data to store."""
    data = {"content_type": msg.content_type.value}

    if msg.text:
        data["text"] = msg.html_text
    if msg.caption:
        data["caption"] = msg.html_text  # use html for formatting

    if msg.photo:
        data["file_id"] = msg.photo[-1].file_id
    elif msg.video:
        data["file_id"] = msg.video.file_id
    elif msg.document:
        data["file_id"] = msg.document.file_id
    elif msg.sticker:
        data["file_id"] = msg.sticker.file_id
    elif msg.animation:
        data["file_id"] = msg.animation.file_id
    elif msg.voice:
        data["file_id"] = msg.voice.file_id
    elif msg.audio:
        data["file_id"] = msg.audio.file_id

    # Inline keyboard buttons (if forwarded message had them - won't be available directly)
    if msg.reply_markup:
        try:
            buttons = []
            for row in msg.reply_markup.inline_keyboard:
                btn_row = []
                for btn in row:
                    btn_row.append({"text": btn.text, "url": btn.url, "callback_data": btn.callback_data})
                buttons.append(btn_row)
            data["buttons"] = buttons
        except Exception:
            pass

    return data


@router.message(ScenarioFSM.waiting_message)
async def fsm_got_message(message: Message, state: FSMContext):
    data = await state.get_data()
    step_id = data["step_id"]
    bot_id = data["bot_id"]

    msg_data = await _serialize_message(message)
    has_buttons = bool(msg_data.get("buttons"))

    async with db() as session:
        step = await session.get(ScenarioStep, step_id)
        step.message_data = msg_data
        step.has_buttons = has_buttons

    await state.clear()
    await message.answer(
        f"✅ Сообщение сохранено!\n"
        f"Тип: <b>{msg_data['content_type']}</b> | Кнопки: {'да' if has_buttons else 'нет'}",
        reply_markup=step_menu_kb(step_id, bot_id, step.step_type)
    )


# ─── Step menu ───────────────────────────────────────────────────

@router.callback_query(F.data.startswith("step_menu:"))
async def cb_step_menu(callback: CallbackQuery):
    step_id = int(callback.data.split(":")[1])
    async with db() as session:
        step = await session.get(ScenarioStep, step_id)

    if not step:
        await callback.answer("Шаг не найден.", show_alert=True)
        return

    icons = {"message": "💬", "op": "🔒", "wait": "⏳"}
    text = (
        f"{icons.get(step.step_type, '❓')} <b>Шаг {step.position + 1} — {step.step_type}</b>\n\n"
        f"📩 Сообщение: {'✅ задано' if step.message_data else '❌ не задано'}\n"
        f"⏱ Задержка после шага: {step.delay_after} сек\n"
        f"🔔 Текст ожидания: {'✅' if step.waiting_text else '❌'}"
    )
    await callback.message.edit_text(text, reply_markup=step_menu_kb(step_id, step.bot_id, step.step_type))
    await callback.answer()


# ─── Delay settings ──────────────────────────────────────────────

@router.callback_query(F.data.startswith("set_delay:"))
async def cb_set_delay(callback: CallbackQuery, state: FSMContext):
    step_id = int(callback.data.split(":")[1])
    await state.update_data(step_id=step_id)
    await state.set_state(ScenarioFSM.waiting_delay)
    await callback.message.edit_text(
        "⏱ Введите задержку в секундах после выполнения этого шага.\n"
        "<i>0 = сразу перейти к следующему шагу</i>",
        reply_markup=cancel_kb(f"step_menu:{step_id}")
    )
    await callback.answer()


@router.message(ScenarioFSM.waiting_delay)
async def fsm_got_delay(message: Message, state: FSMContext):
    text = message.text.strip()
    if not text.isdigit():
        await message.answer("❌ Введите число:")
        return
    data = await state.get_data()
    step_id = data["step_id"]
    async with db() as session:
        step = await session.get(ScenarioStep, step_id)
        step.delay_after = int(text)
    await state.clear()
    await message.answer(f"✅ Задержка установлена: {text} сек.", reply_markup=back_kb(f"step_menu:{step_id}"))


# ─── Waiting text ─────────────────────────────────────────────────

@router.callback_query(F.data.startswith("set_wait_text:"))
async def cb_set_wait_text(callback: CallbackQuery, state: FSMContext):
    step_id = int(callback.data.split(":")[1])
    await state.update_data(step_id=step_id)
    await state.set_state(ScenarioFSM.waiting_wait_text)
    await callback.message.edit_text(
        "🔔 Введите текст, который увидит пользователь во время ожидания задержки.\n"
        "<i>Например: «⏳ Подождите немного...»</i>",
        reply_markup=cancel_kb(f"step_menu:{step_id}")
    )
    await callback.answer()


@router.message(ScenarioFSM.waiting_wait_text)
async def fsm_got_wait_text(message: Message, state: FSMContext):
    data = await state.get_data()
    step_id = data["step_id"]
    async with db() as session:
        step = await session.get(ScenarioStep, step_id)
        step.waiting_text = message.html_text
    await state.clear()
    await message.answer("✅ Текст ожидания сохранён.", reply_markup=back_kb(f"step_menu:{step_id}"))


# ─── Sponsors ─────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("sponsors:"))
async def cb_sponsors(callback: CallbackQuery):
    step_id = int(callback.data.split(":")[1])
    async with db() as session:
        result = await session.execute(select(Sponsor).where(Sponsor.step_id == step_id))
        sponsors = result.scalars().all()

    await callback.message.edit_text(
        f"📢 <b>Спонсоры шага</b> ({len(sponsors)}):\n"
        "<i>Нажмите на спонсора, чтобы удалить его.</i>",
        reply_markup=sponsors_kb(step_id, sponsors)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("add_sponsor:"))
async def cb_add_sponsor(callback: CallbackQuery, state: FSMContext):
    step_id = int(callback.data.split(":")[1])
    await state.update_data(step_id=step_id)
    await state.set_state(ScenarioFSM.waiting_sponsor_title)
    await callback.message.edit_text(
        "📢 <b>Добавление спонсора</b>\n\nВведите <b>название</b> канала/спонсора:",
        reply_markup=cancel_kb(f"sponsors:{step_id}")
    )
    await callback.answer()


@router.message(ScenarioFSM.waiting_sponsor_title)
async def fsm_sponsor_title(message: Message, state: FSMContext):
    await state.update_data(sp_title=message.text.strip())
    await state.set_state(ScenarioFSM.waiting_sponsor_url)
    await message.answer(
        "🔗 Введите <b>ссылку</b> на канал (например: https://t.me/channel):"
    )


@router.message(ScenarioFSM.waiting_sponsor_url)
async def fsm_sponsor_url(message: Message, state: FSMContext):
    await state.update_data(sp_url=message.text.strip())
    await state.set_state(ScenarioFSM.waiting_sponsor_channel_id)
    await message.answer(
        "🆔 Введите <b>ID канала</b> для проверки подписки (например: -1001234567890).\n"
        "Введите <b>0</b>, если проверка не нужна.\n\n"
        "<i>Чтобы узнать ID: добавьте бота в канал как администратора, "
        "затем перешлите сообщение из канала боту @userinfobot</i>"
    )


@router.message(ScenarioFSM.waiting_sponsor_channel_id)
async def fsm_sponsor_channel_id(message: Message, state: FSMContext):
    text = message.text.strip()
    try:
        channel_id = int(text)
    except ValueError:
        await message.answer("❌ Введите числовой ID канала или 0:")
        return

    data = await state.get_data()
    step_id = data["step_id"]
    await state.clear()

    async with db() as session:
        sp = Sponsor(
            step_id=step_id,
            title=data["sp_title"],
            url=data["sp_url"],
            channel_id=channel_id if channel_id != 0 else None
        )
        session.add(sp)

    async with db() as session:
        result = await session.execute(select(Sponsor).where(Sponsor.step_id == step_id))
        sponsors = result.scalars().all()

    await message.answer(
        f"✅ Спонсор <b>{data['sp_title']}</b> добавлен!",
        reply_markup=sponsors_kb(step_id, sponsors)
    )


@router.callback_query(F.data.startswith("del_sponsor:"))
async def cb_del_sponsor(callback: CallbackQuery):
    _, sp_id_str, step_id_str = callback.data.split(":")
    sp_id, step_id = int(sp_id_str), int(step_id_str)

    async with db() as session:
        sp = await session.get(Sponsor, sp_id)
        if sp:
            await session.delete(sp)

    async with db() as session:
        result = await session.execute(select(Sponsor).where(Sponsor.step_id == step_id))
        sponsors = result.scalars().all()

    await callback.message.edit_text(
        f"🗑 Спонсор удалён. Осталось: {len(sponsors)}",
        reply_markup=sponsors_kb(step_id, sponsors)
    )
    await callback.answer("Удалено")


# ─── Reorder / Delete steps ──────────────────────────────────────

@router.callback_query(F.data.startswith("step_up:"))
async def cb_step_up(callback: CallbackQuery):
    _, step_id_str, bot_id_str = callback.data.split(":")
    step_id, bot_id = int(step_id_str), int(bot_id_str)
    await _swap_steps(bot_id, step_id, direction=-1)
    await cb_scenario_refresh(callback, bot_id)


@router.callback_query(F.data.startswith("step_down:"))
async def cb_step_down(callback: CallbackQuery):
    _, step_id_str, bot_id_str = callback.data.split(":")
    step_id, bot_id = int(step_id_str), int(bot_id_str)
    await _swap_steps(bot_id, step_id, direction=1)
    await cb_scenario_refresh(callback, bot_id)


async def _swap_steps(bot_id: int, step_id: int, direction: int):
    async with db() as session:
        result = await session.execute(
            select(ScenarioStep).where(ScenarioStep.bot_id == bot_id).order_by(ScenarioStep.position)
        )
        steps = result.scalars().all()
        for i, s in enumerate(steps):
            if s.id == step_id:
                j = i + direction
                if 0 <= j < len(steps):
                    steps[i].position, steps[j].position = steps[j].position, steps[i].position
                break


async def cb_scenario_refresh(callback: CallbackQuery, bot_id: int):
    async with db() as session:
        result = await session.execute(
            select(ScenarioStep).where(ScenarioStep.bot_id == bot_id).order_by(ScenarioStep.position)
        )
        steps = result.scalars().all()
    await callback.message.edit_text(
        f"📋 <b>Сценарий бота</b>\nШагов: {len(steps)}",
        reply_markup=scenario_menu_kb(bot_id, steps)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("delete_step:"))
async def cb_delete_step(callback: CallbackQuery):
    parts = callback.data.split(":")
    step_id, bot_id = int(parts[1]), int(parts[2])
    async with db() as session:
        step = await session.get(ScenarioStep, step_id)
        if step:
            await session.delete(step)
    await callback.answer("🗑 Шаг удалён")
    await cb_scenario_refresh(callback, bot_id)
