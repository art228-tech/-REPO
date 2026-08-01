"""Главное меню и общие команды."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from tgparser.bot.context import BotContext
from tgparser.bot.keyboards import main_menu
from tgparser.db.repo import AccountRepo, LeadRepo
from tgparser.db.settings_store import load_settings

router = Router(name="common")

WELCOME = (
    "<b>Парсер тематических чатов</b>\n\n"
    "Обходит чаты и каналы подключённого аккаунта, собирает участников "
    "и авторов сообщений в базу без повторов.\n\n"
    "Пользователей без @тега пересылает карточкой в архивный канал — "
    "канал создаётся сам при первой такой находке."
)


async def menu_text(ctx: BotContext) -> str:
    async with ctx.db.session() as session:
        account = await AccountRepo(session).first_active()
        stats = await LeadRepo(session).stats()
        scan_settings = await load_settings(session)

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
    if ctx.scan.is_running:
        lines.append("")
        lines.append("Обход идёт.")
    return "\n".join(lines)


@router.message(CommandStart())
async def on_start(message: Message, ctx: BotContext, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        await menu_text(ctx),
        reply_markup=main_menu(await ctx.has_account(), ctx.scan.is_running),
    )


@router.message(Command("menu"))
async def on_menu(message: Message, ctx: BotContext, state: FSMContext) -> None:
    await on_start(message, ctx, state)


@router.message(Command("cancel"))
async def on_cancel(message: Message, ctx: BotContext, state: FSMContext) -> None:
    await state.clear()
    await ctx.auth.cancel(message.from_user.id)
    await message.answer("Отменил. /menu — вернуться в меню.")


@router.callback_query(F.data == "menu:main")
async def on_menu_callback(call: CallbackQuery, ctx: BotContext, state: FSMContext) -> None:
    await state.clear()
    await call.message.edit_text(
        await menu_text(ctx),
        reply_markup=main_menu(await ctx.has_account(), ctx.scan.is_running),
    )
    await call.answer()
