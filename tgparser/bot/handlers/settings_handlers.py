"""Настройки обхода."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from tgparser.bot.context import BotContext
from tgparser.bot.keyboards import (
    back_to,
    chats_menu,
    depth_menu,
    pace_menu,
    settings_menu,
)
from tgparser.bot.states import SettingsFlow
from tgparser.core.util import parse_chat_list
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


CHATS_HEADER = (
    "<b>Отбор чатов</b>\n\n"
    "«Только эти» — обходим лишь перечисленные, всё остальное пропускаем. "
    "Полезно, когда включаете перебор участников: держите список коротким.\n"
    "«Исключить» — наоборот, пропускаем перечисленные.\n"
    "«Минимум участников» — пропускать чаты меньше указанного размера."
)

CHAT_LIST_PROMPT = (
    "Пришлите чаты одним сообщением — через пробел, запятую или с новой "
    "строки. Понимаю <code>@тег</code>, ссылку <code>t.me/name</code> и "
    "числовой id вида <code>-1001234567890</code>."
)


async def _render_chats(call: CallbackQuery, ctx: BotContext) -> None:
    async with ctx.db.session() as session:
        scan_settings = await load_settings(session, call.from_user.id)

    lines = [CHATS_HEADER]
    if scan_settings.included_chats:
        lines.append("")
        lines.append("Только эти: " + ", ".join(scan_settings.included_chats[:20]))
    if scan_settings.excluded_chats:
        lines.append("")
        lines.append("Исключены: " + ", ".join(scan_settings.excluded_chats[:20]))

    await call.message.edit_text(
        "\n".join(lines), reply_markup=chats_menu(scan_settings)
    )


@router.callback_query(F.data == "settings:chats")
async def on_chats_menu(call: CallbackQuery, ctx: BotContext, state: FSMContext) -> None:
    await state.clear()
    await _render_chats(call, ctx)
    await call.answer()


@router.callback_query(F.data == "settings:chats:only")
async def on_only_prompt(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SettingsFlow.included_chats)
    await call.message.edit_text(
        f"<b>Только эти чаты</b>\n\n{CHAT_LIST_PROMPT}",
        reply_markup=back_to("settings:chats"),
    )
    await call.answer()


@router.callback_query(F.data == "settings:chats:skip")
async def on_skip_prompt(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SettingsFlow.excluded_chats)
    await call.message.edit_text(
        f"<b>Исключить чаты</b>\n\n{CHAT_LIST_PROMPT}",
        reply_markup=back_to("settings:chats"),
    )
    await call.answer()


@router.callback_query(F.data == "settings:chats:min")
async def on_min_prompt(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SettingsFlow.min_participants)
    await call.message.edit_text(
        "Пришлите число: чаты меньше этого размера будут пропускаться. "
        "0 — без ограничения.",
        reply_markup=back_to("settings:chats"),
    )
    await call.answer()


@router.callback_query(F.data.startswith("settings:chats:clear:"))
async def on_clear_list(call: CallbackQuery, ctx: BotContext) -> None:
    which = call.data.rsplit(":", 1)[-1]
    owner_id = call.from_user.id
    async with ctx.db.session() as session:
        scan_settings = await load_settings(session, owner_id)
        if which == "only":
            scan_settings.included_chats = []
        else:
            scan_settings.excluded_chats = []
        await save_settings(session, owner_id, scan_settings)

    await _render_chats(call, ctx)
    await call.answer("Сбросил.")


@router.message(SettingsFlow.included_chats)
async def on_included_chats(message: Message, ctx: BotContext, state: FSMContext) -> None:
    await _save_chat_list(message, ctx, state, "included_chats")


@router.message(SettingsFlow.excluded_chats)
async def on_excluded_chats(message: Message, ctx: BotContext, state: FSMContext) -> None:
    await _save_chat_list(message, ctx, state, "excluded_chats")


async def _save_chat_list(
    message: Message, ctx: BotContext, state: FSMContext, field: str
) -> None:
    chats = parse_chat_list(message.text or "")
    if not chats:
        await message.answer(
            "Ни одного чата не распознал. Нужны @теги, ссылки t.me или числовые id."
        )
        return

    owner_id = message.from_user.id
    async with ctx.db.session() as session:
        scan_settings = await load_settings(session, owner_id)
        setattr(scan_settings, field, chats)
        await save_settings(session, owner_id, scan_settings)

    await state.clear()
    await message.answer(
        f"Сохранил {len(chats)}: " + ", ".join(chats[:20]),
        reply_markup=back_to("settings:chats"),
    )


@router.message(SettingsFlow.min_participants)
async def on_min_participants(message: Message, ctx: BotContext, state: FSMContext) -> None:
    try:
        value = int((message.text or "").strip())
    except ValueError:
        await message.answer("Нужно целое число, 0 — без ограничения.")
        return
    if value < 0:
        await message.answer("Отрицательное не подходит.")
        return

    owner_id = message.from_user.id
    async with ctx.db.session() as session:
        scan_settings = await load_settings(session, owner_id)
        scan_settings.min_participants = value
        await save_settings(session, owner_id, scan_settings)

    await state.clear()
    await message.answer(
        "Сохранил: "
        + ("без ограничения" if value == 0 else f"пропускать чаты меньше {value}"),
        reply_markup=back_to("settings:chats"),
    )


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
