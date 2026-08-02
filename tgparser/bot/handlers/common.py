"""Главное меню и общие команды."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from tgparser.bot.context import BotContext
from tgparser.bot.keyboards import back_to, main_menu
from tgparser.db.repo import AccountRepo, LeadRepo, global_stats
from tgparser.db.settings_store import load_settings

router = Router(name="common")

WELCOME = (
    "<b>Парсер тематических чатов</b>\n\n"
    "Обходит чаты и каналы подключённого аккаунта, собирает участников "
    "и авторов сообщений в базу без повторов.\n\n"
    "Пользователей без @тега пересылает карточкой в архивный канал — "
    "канал создаётся сам при первой такой находке."
)


async def menu_text(ctx: BotContext, owner_id: int, scanning: bool) -> str:
    async with ctx.db.session() as session:
        account = await AccountRepo(session, owner_id).first_active()
        stats = await LeadRepo(session, owner_id).stats()
        scan_settings = await load_settings(session, owner_id)

    lines = [WELCOME, ""]
    if account is None:
        lines.append("Аккаунт не подключён.")
        return "\n".join(lines)

    who = f"@{account.username}" if account.username else account.phone
    lines.append(f"Аккаунт: <b>{who}</b>")
    if AccountRepo.is_blocked(account):
        lines.append(
            f"⚠️ Выведен из работы до {account.blocked_until:%d.%m %H:%M} — "
            f"{account.block_reason}"
        )

    depth = (
        "без ограничения"
        if scan_settings.history_depth_days <= 0
        else f"{scan_settings.history_depth_days} дн."
    )
    sources = []
    if scan_settings.collect_history:
        sources.append("сообщения")
    if scan_settings.collect_comments:
        sources.append("комментарии")
    if scan_settings.collect_roster:
        sources.append("участники")

    lines.append(f"Собираем: {', '.join(sources) if sources else 'ничего не выбрано'}")
    lines.append(f"Глубина: {depth}")
    lines.append("")
    lines.append(
        f"В базе: <b>{stats['leads']}</b> "
        f"(с тегом {stats['with_username']}, карточек {stats['archived_cards']})"
    )
    if scanning:
        lines.append("")
        lines.append("Обход идёт.")
    return "\n".join(lines)


async def show_menu(target: Message | CallbackQuery, ctx: BotContext, edit: bool) -> None:
    owner_id = target.from_user.id
    scanning = ctx.scan.is_running(owner_id)
    text = await menu_text(ctx, owner_id, scanning)
    markup = main_menu(await ctx.has_account(owner_id), scanning)
    if edit and isinstance(target, CallbackQuery):
        await target.message.edit_text(text, reply_markup=markup)
    else:
        message = target.message if isinstance(target, CallbackQuery) else target
        await message.answer(text, reply_markup=markup)


@router.message(CommandStart())
async def on_start(message: Message, ctx: BotContext, state: FSMContext) -> None:
    await state.clear()
    await show_menu(message, ctx, edit=False)


@router.message(Command("menu"))
async def on_menu(message: Message, ctx: BotContext, state: FSMContext) -> None:
    await state.clear()
    await show_menu(message, ctx, edit=False)


@router.message(Command("cancel"))
async def on_cancel(message: Message, ctx: BotContext, state: FSMContext) -> None:
    await state.clear()
    await ctx.auth.cancel(message.from_user.id)
    await message.answer("Отменил. /menu — вернуться в меню.")


@router.message(Command("admin"))
async def on_admin(message: Message, ctx: BotContext) -> None:
    if not ctx.app_settings.is_admin(message.from_user.id):
        await message.answer("Не понял. /menu — открыть меню.")
        return

    async with ctx.db.session() as session:
        stats = await global_stats(session)

    await message.answer(
        "<b>Сводка по боту</b>\n\n"
        f"Пользователей: {stats['users']}\n"
        f"Подключено аккаунтов: {stats['accounts']}\n"
        f"Записей во всех базах: {stats['leads']}\n"
        f"Аккаунтов под ограничением: {stats['blocked']}\n"
        f"Обходов сейчас идёт: {ctx.scan.running_count}\n\n"
        f"Режим доступа: {ctx.app_settings.access_mode}",
        reply_markup=back_to("menu:main"),
    )


@router.callback_query(F.data == "menu:main")
async def on_menu_callback(call: CallbackQuery, ctx: BotContext, state: FSMContext) -> None:
    await state.clear()
    await show_menu(call, ctx, edit=True)
    await call.answer()
