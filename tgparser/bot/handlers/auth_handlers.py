"""Подключение аккаунта: номер сообщением, код — только кнопками."""

from __future__ import annotations

import contextlib

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from tgparser.bot.context import BotContext
from tgparser.bot.keyboards import account_menu, back_to, code_keypad, main_menu
from tgparser.bot.states import AuthFlow
from tgparser.db.repo import AccountRepo
from tgparser.userbot.auth import Outcome
from tgparser.userbot.proxy import redact_proxy

router = Router(name="auth")

PHONE_PROMPT = (
    "Пришлите номер аккаунта в формате <code>+79991234567</code>.\n\n"
    "Код подтверждения потом набирается кнопками — присылать его сообщением "
    "нельзя: Telegram гасит коды, отправленные внутри мессенджера.\n\n"
    "<b>Что это значит.</b> Бот получает полный доступ к аккаунту и хранит "
    "сессию в зашифрованном виде на сервере, где он запущен. Подключайте "
    "аккаунт, только если доверяете владельцу этого сервера. Отключить можно "
    "в любой момент кнопкой «Аккаунт», а завершить сессию принудительно — "
    "в настройках Telegram, раздел «Устройства»."
)

CODE_PROMPT = (
    "Telegram отправил код на аккаунт.\n\n"
    "Наберите его кнопками ниже и нажмите «Готово». "
    "<b>Не пересылайте и не отправляйте код сообщением</b> — он сразу станет "
    "недействительным."
)


@router.callback_query(F.data == "auth:start")
async def on_auth_start(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AuthFlow.phone)
    await call.message.edit_text(PHONE_PROMPT, reply_markup=back_to("menu:main"))
    await call.answer()


@router.message(Command("login"))
async def on_login_command(message: Message, state: FSMContext) -> None:
    await state.set_state(AuthFlow.phone)
    await message.answer(PHONE_PROMPT)


@router.message(AuthFlow.phone)
async def on_phone(message: Message, ctx: BotContext, state: FSMContext) -> None:
    result = await ctx.auth.start(message.from_user.id, message.text or "")
    if result.outcome is not Outcome.CODE_SENT:
        await message.answer(result.message)
        return

    pending = ctx.auth.get(message.from_user.id)
    await state.clear()
    await message.answer(CODE_PROMPT, reply_markup=code_keypad(pending.masked if pending else ""))


@router.callback_query(F.data == "code:noop")
async def on_noop(call: CallbackQuery) -> None:
    await call.answer()


@router.callback_query(F.data.startswith("code:digit:"))
async def on_digit(call: CallbackQuery, ctx: BotContext) -> None:
    digit = call.data.rsplit(":", 1)[-1]
    pending = ctx.auth.push_digit(call.from_user.id, digit)
    if pending is None:
        await call.answer("Сессия входа истекла, начните заново.", show_alert=True)
        return
    await _refresh_keypad(call, pending.masked)
    await call.answer()


@router.callback_query(F.data == "code:back")
async def on_backspace(call: CallbackQuery, ctx: BotContext) -> None:
    pending = ctx.auth.backspace(call.from_user.id)
    if pending is None:
        await call.answer("Сессия входа истекла, начните заново.", show_alert=True)
        return
    await _refresh_keypad(call, pending.masked)
    await call.answer()


@router.callback_query(F.data == "code:cancel")
async def on_cancel_code(call: CallbackQuery, ctx: BotContext) -> None:
    await ctx.auth.cancel(call.from_user.id)
    await call.message.edit_text(
        "Вход отменён.",
        reply_markup=main_menu(
            await ctx.has_account(call.from_user.id),
            ctx.scan.is_running(call.from_user.id),
        ),
    )
    await call.answer()


@router.callback_query(F.data == "code:submit")
async def on_submit(call: CallbackQuery, ctx: BotContext, state: FSMContext) -> None:
    await call.answer("Проверяю…")
    result = await ctx.auth.submit_code(call.from_user.id)

    if result.outcome is Outcome.SIGNED_IN:
        await call.message.edit_text(
            f"{result.message}\n\nМожно запускать обход.",
            reply_markup=main_menu(True, ctx.scan.is_running(call.from_user.id)),
        )
        return

    if result.outcome is Outcome.NEEDS_PASSWORD:
        await state.set_state(AuthFlow.password)
        await call.message.edit_text(result.message)
        return

    if result.outcome is Outcome.INVALID_CODE:
        pending = ctx.auth.get(call.from_user.id)
        await call.message.edit_text(
            f"{result.message}\n\n{CODE_PROMPT}",
            reply_markup=code_keypad(pending.masked if pending else ""),
        )
        return

    await call.message.edit_text(result.message, reply_markup=back_to("menu:main"))


@router.message(AuthFlow.password)
async def on_password(message: Message, ctx: BotContext, state: FSMContext) -> None:
    password = message.text or ""
    # Пароль не должен оставаться в переписке.
    with contextlib.suppress(TelegramBadRequest):
        await message.delete()

    result = await ctx.auth.submit_password(message.from_user.id, password)
    if result.outcome is Outcome.SIGNED_IN:
        await state.clear()
        await message.answer(
            f"{result.message}\n\nПароль удалил из чата. Можно запускать обход.",
            reply_markup=main_menu(True, ctx.scan.is_running(message.from_user.id)),
        )
        return
    if result.outcome is Outcome.INVALID_PASSWORD:
        await message.answer(result.message)
        return
    await state.clear()
    await message.answer(result.message, reply_markup=back_to("menu:main"))


@router.callback_query(F.data == "auth:info")
async def on_account_info(call: CallbackQuery, ctx: BotContext) -> None:
    owner_id = call.from_user.id
    async with ctx.db.session() as session:
        account = await AccountRepo(session, owner_id).first_active()

    if account is None:
        await call.message.edit_text(
            "Аккаунт не подключён.", reply_markup=main_menu(False, False)
        )
        await call.answer()
        return

    lines = [
        "<b>Подключённый аккаунт</b>",
        "",
        f"Номер: <code>{account.phone}</code>",
        f"Тег: {'@' + account.username if account.username else 'нет'}",
        f"ID: <code>{account.tg_user_id}</code>",
        f"Прокси: {redact_proxy(account.proxy)}",
        f"Архивный канал: {'создан' if account.archive_channel_id else 'ещё не создан'}",
    ]
    if AccountRepo.is_blocked(account):
        lines.append("")
        lines.append(
            f"⚠️ Выведен из работы до {account.blocked_until:%d.%m %H:%M}\n"
            f"Причина: {account.block_reason}"
        )
        lines.append(
            "\nЭто защита от повторного срабатывания: продолжать сразу после "
            "PeerFlood — верный способ получить постоянное ограничение."
        )

    await call.message.edit_text("\n".join(lines), reply_markup=account_menu())
    await call.answer()


@router.callback_query(F.data == "auth:logout")
async def on_logout(call: CallbackQuery, ctx: BotContext) -> None:
    async with ctx.db.session() as session:
        repo = AccountRepo(session, call.from_user.id)
        account = await repo.first_active()
        if account is not None:
            await repo.delete(account)
    await call.message.edit_text(
        "Аккаунт отключён, сессия удалена из базы. "
        "Собранные записи остались на месте.",
        reply_markup=main_menu(False, False),
    )
    await call.answer()


async def _refresh_keypad(call: CallbackQuery, masked: str) -> None:
    with contextlib.suppress(TelegramBadRequest):
        await call.message.edit_reply_markup(reply_markup=code_keypad(masked))
