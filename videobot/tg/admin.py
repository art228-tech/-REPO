"""Админка: люди, выдача роликов, статистика."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from .. import stats as stats_module
from ..db import Base
from ..logs import get_logger

log = get_logger("админка")

router = Router()


class Adding(StatesGroup):
    typing_id = State()


class Giving(StatesGroup):
    typing_count = State()


def _only_admin(person) -> bool:
    return bool(person and person["is_admin"])


def _menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Ролики", callback_data="a:videos")],
        [InlineKeyboardButton(text="Выдать ролики", callback_data="a:give")],
        [InlineKeyboardButton(text="Люди", callback_data="a:people")],
        [InlineKeyboardButton(text="Статистика", callback_data="a:stats")],
    ])


async def show_admin_menu(message: Message, base: Base) -> None:
    counts = base.counts()
    await message.answer(
        f"Свободных роликов: {counts['free']}\n"
        f"В очереди на заливку: {counts['pending']}",
        reply_markup=_menu())


@router.callback_query(F.data == "a:menu")
async def back(call: CallbackQuery, base: Base, person, state: FSMContext) -> None:
    if not _only_admin(person):
        await call.answer()
        return
    await state.clear()
    counts = base.counts()
    await call.message.edit_text(
        f"Свободных роликов: {counts['free']}\n"
        f"В очереди на заливку: {counts['pending']}",
        reply_markup=_menu())
    await call.answer()


@router.callback_query(F.data == "a:videos")
async def videos(call: CallbackQuery, base: Base, person) -> None:
    if not _only_admin(person):
        await call.answer()
        return

    counts = base.counts()
    text = [
        f"Свободные, ещё никому не отданы: <b>{counts['free']}</b>",
        f"Всего залито: {counts['ready']}",
        f"Ждут заливки: {counts['pending']}",
    ]
    if counts["failed"]:
        text.append(f"Не залились: {counts['failed']} — смотрите окно программы")

    await call.message.edit_text("\n".join(text), reply_markup=InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Назад", callback_data="a:menu")]]))
    await call.answer()


# --- выдача ---------------------------------------------------------------

def _people_buttons(base: Base, prefix: str, only_allowed: bool = True):
    rows = []
    for row in base.people():
        if row["is_admin"]:
            continue
        if only_allowed and not row["has_access"]:
            continue
        waiting = base.waiting_for(row["tg_id"])
        tail = f" (ждут {waiting})" if waiting else ""
        rows.append([InlineKeyboardButton(
            text=f"{row['name'] or row['tg_id']}{tail}",
            callback_data=f"{prefix}:{row['tg_id']}")])
    rows.append([InlineKeyboardButton(text="Назад", callback_data="a:menu")])
    return rows


@router.callback_query(F.data == "a:give")
async def give_pick(call: CallbackQuery, base: Base, person) -> None:
    if not _only_admin(person):
        await call.answer()
        return

    free = base.counts()["free"]
    if not free:
        await call.answer("Свободных роликов нет", show_alert=True)
        return

    rows = _people_buttons(base, "a:give")
    if len(rows) == 1:
        await call.answer("Некому выдавать: нет людей с доступом", show_alert=True)
        return

    await call.message.edit_text(
        f"Свободных роликов: {free}. Кому выдать?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await call.answer()


@router.callback_query(F.data.startswith("a:give:"))
async def give_count(call: CallbackQuery, base: Base, person, state: FSMContext) -> None:
    if not _only_admin(person):
        await call.answer()
        return

    try:
        target = int(call.data.split(":")[2])
    except (IndexError, ValueError):
        await call.answer()
        return

    free = base.counts()["free"]
    await state.set_state(Giving.typing_count)
    await state.update_data(target=target)

    who = base.person(target)
    await call.message.edit_text(
        f"Кому: <b>{(who['name'] if who else target)}</b>\n"
        f"Свободно: {free}\n\nСколько роликов выдать? Пришлите число.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"Все {free}", callback_data=f"a:go:{target}:{free}")],
            [InlineKeyboardButton(text="Назад", callback_data="a:give")]]))
    await call.answer()


@router.message(Giving.typing_count)
async def give_typed(message: Message, base: Base, person, state: FSMContext) -> None:
    if not _only_admin(person):
        return

    raw = (message.text or "").strip()
    if not raw.isdigit() or int(raw) < 1:
        await message.answer("Нужно число больше нуля.")
        return

    data = await state.get_data()
    await state.clear()
    await _do_give(message, base, int(data.get("target", 0)), int(raw))


@router.callback_query(F.data.startswith("a:go:"))
async def give_all(call: CallbackQuery, base: Base, person, state: FSMContext) -> None:
    if not _only_admin(person):
        await call.answer()
        return
    try:
        _, _, target, count = call.data.split(":")
    except ValueError:
        await call.answer()
        return

    await state.clear()
    await call.answer()
    await _do_give(call.message, base, int(target), int(count))


async def _do_give(message: Message, base: Base, target: int, count: int) -> None:
    given = base.assign(target, count)
    if not given:
        await message.answer("Свободных роликов не осталось.", reply_markup=_menu())
        return

    who = base.person(target)
    log.info("Выдано %d роликов человеку %s (%d)", given, who["name"] if who else "?", target)

    try:
        await message.bot.send_message(
            target,
            f"Вам добавили роликов: {given}.\n"
            "Заберите их в меню — /start.")
    except Exception as exc:  # noqa: BLE001 - уведомление не главное
        log.warning("Уведомить %d не вышло: %s", target, exc)
        await message.answer(
            f"Выдал {given}, но уведомление не дошло: {exc}\n\n"
            "Скорее всего человек ещё ни разу не нажимал «Старт» у бота — "
            "первым писать боту нельзя.", reply_markup=_menu())
        return

    await message.answer(f"Выдал роликов: {given}.", reply_markup=_menu())


# --- люди -----------------------------------------------------------------

@router.callback_query(F.data == "a:people")
async def people(call: CallbackQuery, base: Base, person) -> None:
    if not _only_admin(person):
        await call.answer()
        return

    rows = []
    for row in base.people():
        if row["is_admin"]:
            continue
        mark = "есть доступ" if row["has_access"] else "без доступа"
        rows.append([InlineKeyboardButton(
            text=f"{row['name'] or row['tg_id']} — {mark}",
            callback_data=f"a:person:{row['tg_id']}")])

    rows.append([InlineKeyboardButton(text="Добавить по ID", callback_data="a:add")])
    rows.append([InlineKeyboardButton(text="Назад", callback_data="a:menu")])

    await call.message.edit_text(
        "Нажмите на человека, чтобы дать или отобрать доступ.\n\n"
        "Человек должен сам нажать «Старт» у бота — иначе уведомления до него "
        "не дойдут, Telegram запрещает ботам писать первыми.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await call.answer()


@router.callback_query(F.data.startswith("a:person:"))
async def toggle(call: CallbackQuery, base: Base, person) -> None:
    if not _only_admin(person):
        await call.answer()
        return

    try:
        target = int(call.data.split(":")[2])
    except (IndexError, ValueError):
        await call.answer()
        return

    who = base.person(target)
    if who is None:
        await call.answer("Не найден")
        return

    allowed = not who["has_access"]
    base.set_access(target, allowed)

    if not allowed:
        # Доступ отобрали — забираем всё, что человек не успел скачать.
        # Скачанное остаётся за ним: по нему уже есть или будут просмотры.
        returned = base.take_back(target)
        log.info("Доступ отобран у %d, возвращено роликов: %d", target, returned)
        await call.answer(f"Доступ закрыт, вернул роликов: {returned}", show_alert=True)
    else:
        log.info("Доступ выдан %d", target)
        await call.answer("Доступ открыт")

    await people(call, base, person)


@router.callback_query(F.data == "a:add")
async def add_ask(call: CallbackQuery, person, state: FSMContext) -> None:
    if not _only_admin(person):
        await call.answer()
        return

    await state.set_state(Adding.typing_id)
    await call.message.edit_text(
        "Пришлите числовой ID человека.\n\n"
        "Он узнаёт его так: открывает бота, жмёт «Старт» — и бот запомнит его. "
        "После этого ID можно взять здесь же, в списке людей.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Назад", callback_data="a:people")]]))
    await call.answer()


@router.message(Adding.typing_id)
async def add_typed(message: Message, base: Base, person, state: FSMContext) -> None:
    if not _only_admin(person):
        return

    raw = (message.text or "").strip()
    if not raw.isdigit():
        await message.answer("ID — это число. Например: 123456789")
        return

    target = int(raw)
    base.set_access(target, True)
    await state.clear()
    log.info("Доступ выдан %d", target)

    known = base.person(target)
    tail = ""
    if not known or not known["name"]:
        tail = ("\n\nОн ещё ни разу не открывал бота. Пока не нажмёт «Старт», "
                "уведомления до него не дойдут.")

    await message.answer(f"Доступ открыт: {target}.{tail}", reply_markup=_menu())


# --- статистика -----------------------------------------------------------

@router.callback_query(F.data == "a:stats")
async def stats_all(call: CallbackQuery, base: Base, person) -> None:
    if not _only_admin(person):
        await call.answer()
        return
    await _show_stats(call, base, owner=None)


@router.callback_query(F.data == "a:statspick")
async def stats_pick(call: CallbackQuery, base: Base, person) -> None:
    if not _only_admin(person):
        await call.answer()
        return

    rows = _people_buttons(base, "a:stats", only_allowed=False)
    await call.message.edit_text(
        "По кому смотреть?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await call.answer()


@router.callback_query(F.data.startswith("a:stats:"))
async def stats_one(call: CallbackQuery, base: Base, person) -> None:
    if not _only_admin(person):
        await call.answer()
        return
    try:
        target = int(call.data.split(":")[2])
    except (IndexError, ValueError):
        await call.answer()
        return
    await _show_stats(call, base, owner=target)


async def _show_stats(call: CallbackQuery, base: Base, owner: int | None) -> None:
    rows = base.measured()
    if owner is not None:
        rows = [row for row in rows if row["owner_id"] == owner]

    counts = base.counts()
    skipped = max(0, counts["ready"] - len(rows))

    who = base.person(owner) if owner is not None else None
    title = f"Статистика — {who['name'] if who else owner}" if owner is not None \
        else "Статистика — все"

    text = title + "\n\n" + stats_module.describe(
        stats_module.report(rows), total=len(rows), skipped=skipped)

    switch = InlineKeyboardButton(
        text="Все" if owner is not None else "По людям",
        callback_data="a:stats" if owner is not None else "a:statspick")

    await call.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [switch],
        [InlineKeyboardButton(text="Назад", callback_data="a:menu")]]))
    await call.answer()
