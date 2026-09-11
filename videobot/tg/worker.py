"""Меню человека: забрать ролики и вписать просмотры."""
from __future__ import annotations

import asyncio

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from ..db import Base
from ..logs import get_logger

log = get_logger("меню")

router = Router()

# Пауза между файлами: ролики уходят по одному, а не пачкой разом. Telegram
# ограничивает частоту отправки, и без паузы на десятке файлов он начинает
# отвечать отказами, а человек видит половину выдачи.
BETWEEN_FILES_S = 1.0


class Views(StatesGroup):
    typing = State()


def menu(waiting: int) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(
        text=f"Забрать ролики ({waiting})" if waiting else "Роликов пока нет",
        callback_data="take" if waiting else "nothing")]]
    rows.append([InlineKeyboardButton(text="История и просмотры", callback_data="hist")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _counts(waiting: int, limit: int) -> InlineKeyboardMarkup:
    top = min(waiting, limit)
    steps = [value for value in (1, 5, 10, 25) if value < top]
    rows = [[InlineKeyboardButton(text=str(value), callback_data=f"take:{value}")
             for value in steps]] if steps else []
    rows.append([InlineKeyboardButton(text=f"Все {top}", callback_data=f"take:{top}")])
    rows.append([InlineKeyboardButton(text="Назад", callback_data="menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(CommandStart())
async def start(message: Message, base: Base, person, state: FSMContext) -> None:
    await state.clear()
    if person["is_admin"]:
        from .admin import show_admin_menu
        await show_admin_menu(message, base)
        return

    waiting = base.waiting_for(person["tg_id"])
    await message.answer(
        "Здесь вы забираете ролики и отмечаете, сколько они набрали.",
        reply_markup=menu(waiting))


@router.callback_query(F.data == "menu")
async def back(call: CallbackQuery, base: Base, person, state: FSMContext) -> None:
    await state.clear()
    waiting = base.waiting_for(person["tg_id"])
    await call.message.edit_text(
        "Здесь вы забираете ролики и отмечаете, сколько они набрали.",
        reply_markup=menu(waiting))
    await call.answer()


@router.callback_query(F.data == "nothing")
async def nothing(call: CallbackQuery) -> None:
    await call.answer("Новых роликов нет")


@router.callback_query(F.data == "take")
async def ask_count(call: CallbackQuery, base: Base, person, settings) -> None:
    waiting = base.waiting_for(person["tg_id"])
    if not waiting:
        await call.answer("Новых роликов нет")
        return

    limit = settings.max_take_at_once
    note = ""
    if waiting > limit:
        note = f"\n\nЗа раз выдаётся не больше {limit}. Остальные никуда не денутся."

    await call.message.edit_text(
        f"Ждут выдачи: {waiting}. Сколько забрать?{note}",
        reply_markup=_counts(waiting, limit))
    await call.answer()


@router.callback_query(F.data.startswith("take:"))
async def hand_over(call: CallbackQuery, base: Base, person, settings) -> None:
    try:
        count = int(call.data.split(":", 1)[1])
    except ValueError:
        await call.answer()
        return

    count = max(1, min(count, settings.max_take_at_once))
    videos = base.next_to_hand_over(person["tg_id"], count)
    if not videos:
        await call.answer("Новых роликов нет")
        return

    await call.message.edit_text(f"Отправляю {len(videos)}, по одному…")
    await call.answer()

    sent = 0
    for video in videos:
        try:
            await call.bot.send_document(
                chat_id=person["tg_id"],
                document=video.file_id,
                caption=video.name,
                disable_notification=True)
        except Exception as exc:  # noqa: BLE001 - один сбой не должен рвать выдачу
            log.error("Ролик %s не ушёл к %s: %s", video.name, person["tg_id"], exc)
            continue

        base.mark_taken(video.id)
        sent += 1
        await asyncio.sleep(BETWEEN_FILES_S)

    left = base.waiting_for(person["tg_id"])
    tail = f"\nОсталось: {left}." if left else ""
    await call.message.answer(
        f"Отправлено роликов: {sent}.{tail}\n\n"
        "Когда выложите — впишите просмотры в истории.",
        reply_markup=menu(left))


@router.callback_query(F.data == "hist")
async def history(call: CallbackQuery, base: Base, person) -> None:
    rows = base.history(person["tg_id"], limit=20)
    if not rows:
        await call.message.edit_text(
            "Вы ещё не забирали ролики.", reply_markup=menu(base.waiting_for(person["tg_id"])))
        await call.answer()
        return

    buttons = []
    for row in rows:
        seen = row["last_views"]
        mark = f"{seen:,}".replace(",", " ") if seen is not None else "нет данных"
        buttons.append([InlineKeyboardButton(
            text=f"{row['name']} — {mark}", callback_data=f"views:{row['id']}")])
    buttons.append([InlineKeyboardButton(text="Назад", callback_data="menu")])

    await call.message.edit_text(
        "Выберите ролик, чтобы вписать просмотры.\n"
        "Вписать можно повторно — прежнее значение сохранится.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await call.answer()


@router.callback_query(F.data.startswith("views:"))
async def ask_views(call: CallbackQuery, base: Base, person, state: FSMContext) -> None:
    try:
        video_id = int(call.data.split(":", 1)[1])
    except ValueError:
        await call.answer()
        return

    video = base.video(video_id)
    if video is None or video["owner_id"] != person["tg_id"]:
        await call.answer("Это не ваш ролик")
        return

    await state.set_state(Views.typing)
    await state.update_data(video_id=video_id)
    await call.message.edit_text(
        f"Ролик <b>{video['name']}</b>\n\nСколько просмотров? Пришлите число.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Отмена", callback_data="hist")]]))
    await call.answer()


@router.message(Views.typing)
async def save_views(message: Message, base: Base, person, state: FSMContext) -> None:
    raw = (message.text or "").strip().replace(" ", "").replace(",", "")
    if not raw.isdigit():
        await message.answer("Нужно число, без букв и пробелов. Например: 1000")
        return

    value = int(raw)
    if value > 1_000_000_000:
        await message.answer("Столько просмотров не бывает. Проверьте число.")
        return

    data = await state.get_data()
    video = base.video(int(data.get("video_id", 0)))
    if video is None or video["owner_id"] != person["tg_id"]:
        await state.clear()
        await message.answer("Ролик не найден.")
        return

    base.add_views(video["id"], value)
    await state.clear()
    log.info("Просмотры %s: %d от %s", video["name"], value, person["tg_id"])

    await message.answer(
        f"Записал: {value:,} у ролика {video['name']}.".replace(",", " "),
        reply_markup=menu(base.waiting_for(person["tg_id"])))
