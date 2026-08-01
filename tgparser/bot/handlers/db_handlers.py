"""База: статистика, ручное добавление тегов, выгрузки."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, FSInputFile, Message

from tgparser.bot.context import BotContext
from tgparser.bot.keyboards import back_to, confirm, db_menu, export_menu
from tgparser.bot.states import DatabaseFlow
from tgparser.core.util import extract_usernames
from tgparser.db.repo import AccountRepo, ChatStateRepo, LeadRepo
from tgparser.db.settings_store import load_settings
from tgparser.export.service import ExportFilter, export

router = Router(name="database")


@router.callback_query(F.data == "db:menu")
async def on_db_menu(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await call.message.edit_text(
        "<b>База</b>\n\nРучное добавление, статистика, сброс чекпоинтов.",
        reply_markup=db_menu(),
    )
    await call.answer()


@router.callback_query(F.data == "db:stats")
async def on_stats(call: CallbackQuery, ctx: BotContext) -> None:
    owner_id = call.from_user.id
    async with ctx.db.session() as session:
        stats = await LeadRepo(session, owner_id).stats()
        account = await AccountRepo(session, owner_id).first_active()
        states = await ChatStateRepo(session).for_account(account.id) if account else []

    scanned = sum(1 for s in states if s.history_done or s.roster_done)
    lines = [
        "<b>Статистика</b>",
        "",
        f"Записей всего: <b>{stats['leads']}</b>",
        f"С тегом: {stats['with_username']}",
        f"Без тега: {stats['without_username']}",
        f"Карточек в архиве: {stats['archived_cards']}",
    ]
    if stats["anonymized_cards"]:
        lines.append(
            f"Из них без ссылки на автора: {stats['anonymized_cards']} "
            "(у пользователя закрыты пересылки)"
        )
    lines += [
        f"Добавлено вручную: {stats['manual']}",
        f"Чатов в базе: {stats['chats']}",
        "",
        f"Чатов с чекпоинтами: {len(states)}, из них пройдено: {scanned}",
    ]

    await call.message.edit_text("\n".join(lines), reply_markup=back_to("db:menu"))
    await call.answer()


@router.callback_query(F.data == "db:add")
async def on_add_prompt(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(DatabaseFlow.manual_tags)
    await call.message.edit_text(
        "Пришлите теги одним сообщением — через пробел, запятую или с новой "
        "строки. Ссылки вида <code>t.me/name</code> тоже понимаю.\n\n"
        "Повторы и некорректные значения отсеются сами.",
        reply_markup=back_to("db:menu"),
    )
    await call.answer()


@router.message(DatabaseFlow.manual_tags)
async def on_add_tags(message: Message, ctx: BotContext, state: FSMContext) -> None:
    candidates = extract_usernames(message.text or "")
    if not candidates:
        await message.answer(
            "Ни одного корректного тега не нашёл. Тег — от 5 до 32 символов, "
            "буквы, цифры и подчёркивание, начинается с буквы."
        )
        return

    added, existed = [], []
    async with ctx.db.session() as session:
        repo = LeadRepo(session, message.from_user.id)
        for tag in candidates:
            _, created = await repo.add_manual(tag)
            (added if created else existed).append(tag)

    lines = [f"Добавлено: <b>{len(added)}</b>"]
    if added:
        lines.append(", ".join(f"@{t}" for t in added[:30]))
        if len(added) > 30:
            lines.append(f"…и ещё {len(added) - 30}")
    if existed:
        lines.append("")
        lines.append(f"Уже были в базе: {len(existed)}")

    await state.clear()
    await message.answer("\n".join(lines), reply_markup=back_to("db:menu"))


@router.callback_query(F.data == "db:reset")
async def on_reset_prompt(call: CallbackQuery) -> None:
    await call.message.edit_text(
        "Сбросить чекпоинты обхода?\n\n"
        "Следующий прогон пойдёт по всем чатам с начала. Собранные записи "
        "не удаляются — дедуп не даст создать повторы.",
        reply_markup=confirm("db:reset:yes", "db:menu"),
    )
    await call.answer()


@router.callback_query(F.data == "db:reset:yes")
async def on_reset(call: CallbackQuery, ctx: BotContext) -> None:
    async with ctx.db.session() as session:
        account = await AccountRepo(session, call.from_user.id).first_active()
        count = await ChatStateRepo(session).reset(account.id) if account else 0

    await call.message.edit_text(
        f"Готово, сброшено чатов: {count}.", reply_markup=back_to("db:menu")
    )
    await call.answer()


@router.callback_query(F.data == "export:menu")
async def on_export_menu(call: CallbackQuery, ctx: BotContext) -> None:
    async with ctx.db.session() as session:
        stats = await LeadRepo(session, call.from_user.id).stats()

    await call.message.edit_text(
        f"<b>Выгрузка</b>\n\nВ базе {stats['leads']} записей "
        f"({stats['with_username']} с тегом).\n\n"
        "CSV отдаю с BOM и разделителем «;» — Excel в русской локали "
        "откроет без кракозябр.",
        reply_markup=export_menu(),
    )
    await call.answer()


@router.callback_query(F.data.startswith("export:fmt:"))
async def on_export(call: CallbackQuery, ctx: BotContext) -> None:
    fmt = call.data.rsplit(":", 1)[-1]
    await _send_export(call, ctx, fmt, ExportFilter())


@router.callback_query(F.data.startswith("export:tagged:"))
async def on_export_tagged(call: CallbackQuery, ctx: BotContext) -> None:
    fmt = call.data.rsplit(":", 1)[-1]
    await _send_export(call, ctx, fmt, ExportFilter(only_with_username=True))


async def _send_export(
    call: CallbackQuery, ctx: BotContext, fmt: str, flt: ExportFilter
) -> None:
    await call.answer("Готовлю файл…")
    ctx.app_settings.ensure_dirs()

    owner_id = call.from_user.id
    async with ctx.db.session() as session:
        scan_settings = await load_settings(session, owner_id)
        try:
            result = await export(
                session, owner_id, fmt, ctx.app_settings.export_dir, scan_settings, flt
            )
        except ValueError as exc:
            await call.message.answer(str(exc))
            return

    if result.rows == 0:
        await call.message.answer("Выгружать нечего — база пустая.")
        return

    await call.message.answer_document(
        FSInputFile(result.path),
        caption=f"{result.rows} записей, {flt.describe()}.",
    )
