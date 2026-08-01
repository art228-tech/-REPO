"""Настройки обхода."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from tgparser.bot.context import BotContext
from tgparser.bot.keyboards import back_to, depth_menu, pace_menu, settings_menu
from tgparser.bot.states import SettingsFlow
from tgparser.db.settings_store import load_settings, save_settings

router = Router(name="settings")

TOGGLES = {
    "collect_history",
    "collect_comments",
    "collect_roster",
    "forward_untagged",
    "skip_bots",
    "forum_busiest_topic_only",
}

ROSTER_WARNING = (
    "\n\n⚠️ Перебор списка участников включён. Из всех операций именно она "
    "притягивает PeerFlood — держите бюджет низким и не запускайте её "
    "на многих крупных чатах подряд."
)

SETTINGS_HEADER = "<b>Настройки</b>\n\nЧто собираем и как глубоко."


async def _render(call: CallbackQuery, ctx: BotContext) -> None:
    owner_id = call.from_user.id
    async with ctx.db.session() as session:
        scan_settings = await load_settings(session, owner_id)
    text = SETTINGS_HEADER
    if scan_settings.collect_roster:
        text += ROSTER_WARNING
    await call.message.edit_text(text, reply_markup=settings_menu(scan_settings))


@router.callback_query(F.data == "settings:menu")
async def on_settings(call: CallbackQuery, ctx: BotContext, state: FSMContext) -> None:
    await state.clear()
    await _render(call, ctx)
    await call.answer()


@router.callback_query(F.data.startswith("settings:toggle:"))
async def on_toggle(call: CallbackQuery, ctx: BotContext) -> None:
    field = call.data.rsplit(":", 1)[-1]
    if field not in TOGGLES:
        await call.answer("Неизвестная настройка.", show_alert=True)
        return

    owner_id = call.from_user.id
    async with ctx.db.session() as session:
        scan_settings = await load_settings(session, owner_id)
        setattr(scan_settings, field, not getattr(scan_settings, field))
        await save_settings(session, owner_id, scan_settings)

    await _render(call, ctx)
    await call.answer()


@router.callback_query(F.data == "settings:depth")
async def on_depth_menu(call: CallbackQuery) -> None:
    await call.message.edit_text(
        "<b>Глубина истории</b>\n\n"
        "До какого возраста сообщений идти назад. Чем глубже, тем больше "
        "запросов и дольше прогон.",
        reply_markup=depth_menu(),
    )
    await call.answer()


@router.callback_query(F.data.startswith("settings:depth:"))
async def on_depth_set(call: CallbackQuery, ctx: BotContext) -> None:
    raw = call.data.rsplit(":", 1)[-1]
    try:
        days = int(raw)
    except ValueError:
        await call.answer("Не понял значение.", show_alert=True)
        return

    owner_id = call.from_user.id
    async with ctx.db.session() as session:
        scan_settings = await load_settings(session, owner_id)
        scan_settings.history_depth_days = max(0, days)
        await save_settings(session, owner_id, scan_settings)

    await _render(call, ctx)
    await call.answer("Сохранил.")


@router.callback_query(F.data == "settings:pace")
async def on_pace_menu(call: CallbackQuery, ctx: BotContext) -> None:
    async with ctx.db.session() as session:
        scan_settings = await load_settings(session, call.from_user.id)

    await call.message.edit_text(
        "<b>Темп и лимиты</b>\n\n"
        "Бюджеты запросов в час. История — обычное поведение клиента, ей "
        "бюджет щедрый. Перебор участников бюджетом придушен намеренно.\n\n"
        f"Пауза между запросами: {scan_settings.min_delay_sec}–"
        f"{scan_settings.max_delay_sec} с (случайная).\n"
        f"Порог FloodWait: {scan_settings.max_flood_wait_sec} с — дольше не "
        "пересиживаем, а прерываем прогон.\n"
        f"Пауза после PeerFlood: {scan_settings.peer_flood_cooldown_hours} ч.",
        reply_markup=pace_menu(scan_settings),
    )
    await call.answer()


@router.callback_query(F.data == "settings:pace:roster")
async def on_roster_budget(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SettingsFlow.roster_budget)
    await call.message.edit_text(
        "Сколько запросов списка участников в час разрешить?\n\n"
        "Один запрос отдаёт до 200 человек. По практическим наблюдениям "
        "выше 20–30 в час на крупных чатах начинаются FloodWait.\n\n"
        "Пришлите число.",
        reply_markup=back_to("settings:pace"),
    )
    await call.answer()


@router.callback_query(F.data == "settings:pace:history")
async def on_history_budget(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SettingsFlow.history_budget)
    await call.message.edit_text(
        "Сколько запросов истории в час разрешить?\n\n"
        "Один запрос отдаёт до 100 сообщений вместе с профилями авторов.\n\n"
        "Пришлите число.",
        reply_markup=back_to("settings:pace"),
    )
    await call.answer()


@router.callback_query(F.data == "settings:pace:warmup")
async def on_warmup_reset(call: CallbackQuery, ctx: BotContext) -> None:
    owner_id = call.from_user.id
    async with ctx.db.session() as session:
        scan_settings = await load_settings(session, owner_id)
        if scan_settings.in_warmup:
            scan_settings.warmup_runs_done = scan_settings.warmup_runs_required
            note = "Разгон снят, следующий прогон пойдёт на полном бюджете."
        else:
            scan_settings.warmup_runs_done = 0
            note = "Разгон включён снова: ближайшие прогоны на четверти бюджета."
        await save_settings(session, owner_id, scan_settings)

    await call.answer(note, show_alert=True)
    await on_pace_menu(call, ctx)


@router.message(SettingsFlow.roster_budget)
async def on_roster_budget_value(message: Message, ctx: BotContext, state: FSMContext) -> None:
    await _set_budget(message, ctx, state, "roster_calls_per_hour", 1, 200)


@router.message(SettingsFlow.history_budget)
async def on_history_budget_value(message: Message, ctx: BotContext, state: FSMContext) -> None:
    await _set_budget(message, ctx, state, "history_calls_per_hour", 10, 2000)


async def _set_budget(
    message: Message,
    ctx: BotContext,
    state: FSMContext,
    field: str,
    low: int,
    high: int,
) -> None:
    try:
        value = int((message.text or "").strip())
    except ValueError:
        await message.answer(f"Нужно целое число от {low} до {high}.")
        return
    if not low <= value <= high:
        await message.answer(f"Значение должно быть от {low} до {high}.")
        return

    owner_id = message.from_user.id
    async with ctx.db.session() as session:
        scan_settings = await load_settings(session, owner_id)
        setattr(scan_settings, field, value)
        await save_settings(session, owner_id, scan_settings)

    await state.clear()
    await message.answer(
        f"Сохранил: {value} запросов в час.", reply_markup=back_to("settings:menu")
    )
