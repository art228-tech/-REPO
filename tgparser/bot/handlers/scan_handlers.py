"""Управление обходом."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery

from tgparser.bot.context import BotContext
from tgparser.bot.keyboards import back_to, main_menu
from tgparser.bot.progress import ProgressReporter
from tgparser.bot.scan_service import ScanBusyError, format_report
from tgparser.db.repo import AccountRepo
from tgparser.db.settings_store import load_settings

router = Router(name="scan")


@router.callback_query(F.data.in_({"scan:start", "scan:resume"}))
async def on_scan_start(call: CallbackQuery, ctx: BotContext) -> None:
    resume = call.data == "scan:resume"
    owner_id = call.from_user.id

    async with ctx.db.session() as session:
        account = await AccountRepo(session, owner_id).first_active()
        scan_settings = await load_settings(session, owner_id)

    if account is None:
        await call.answer("Сначала подключите аккаунт.", show_alert=True)
        return
    if AccountRepo.is_blocked(account):
        await call.answer(
            f"Аккаунт выведен из работы до {account.blocked_until:%d.%m %H:%M}: "
            f"{account.block_reason}",
            show_alert=True,
        )
        return
    if not (
        scan_settings.collect_history
        or scan_settings.collect_comments
        or scan_settings.collect_roster
    ):
        await call.answer("В настройках выключены все источники сбора.", show_alert=True)
        return

    header = "<b>Обход</b>" if resume else "<b>Обход с начала</b>"
    message = await call.message.edit_text(f"{header}\n\nПодключаюсь к аккаунту…")
    reporter = ProgressReporter(message, header)

    try:
        await ctx.scan.start(owner_id, resume=resume, on_progress=reporter)
    except ScanBusyError:
        await call.answer("Обход уже идёт.", show_alert=True)
        return

    await call.answer("Запустил.")


@router.callback_query(F.data == "scan:stop")
async def on_scan_stop(call: CallbackQuery, ctx: BotContext) -> None:
    owner_id = call.from_user.id
    stopped = await ctx.scan.stop(owner_id)
    text = (
        "Обход остановлен, прогресс сохранён. Кнопка «Продолжить с места "
        "остановки» вернётся к тому же месту."
        if stopped
        else "Обход и так не идёт."
    )
    await call.message.edit_text(
        text, reply_markup=main_menu(await ctx.has_account(owner_id), False)
    )
    await call.answer()


@router.callback_query(F.data == "scan:status")
async def on_scan_status(call: CallbackQuery, ctx: BotContext) -> None:
    owner_id = call.from_user.id
    if ctx.scan.is_running(owner_id):
        await call.answer("Обход идёт, прогресс в сообщении выше.", show_alert=True)
        return

    error = ctx.scan.last_error(owner_id)
    report = ctx.scan.last_report(owner_id)
    if error:
        await call.message.edit_text(error, reply_markup=back_to("menu:main"))
    elif report is not None:
        await call.message.edit_text(format_report(report), reply_markup=back_to("menu:main"))
    else:
        await call.message.edit_text("Обходов пока не было.", reply_markup=back_to("menu:main"))
    await call.answer()
