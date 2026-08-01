"""Подключение аккаунта: ключи приложения, затем вход по коду."""

from __future__ import annotations

import contextlib

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from tgparser.bot.context import BotContext
from tgparser.bot.keyboards import (
    account_menu,
    back_to,
    code_keypad,
    keys_choice,
    keys_retry,
    main_menu,
)
from tgparser.bot.states import AuthFlow
from tgparser.db.repo import AccountRepo
from tgparser.userbot.auth import Outcome, parse_keys
from tgparser.userbot.proxy import redact_proxy

router = Router(name="auth")

PHONE_PROMPT = (
    "Пришлите номер аккаунта в формате <code>+79991234567</code>.\n\n"
    "<b>Что это значит.</b> Бот получает полный доступ к аккаунту и хранит "
    "сессию в зашифрованном виде на сервере, где он запущен. Подключайте "
    "аккаунт, только если доверяете владельцу этого сервера. Отключить можно "
    "кнопкой «Аккаунт», а завершить сессию принудительно — в настройках "
    "Telegram, раздел «Устройства»."
)

KEYS_PROMPT = (
    "Нужны <b>api_id</b> и <b>api_hash</b> — это ключи приложения. "
    "Они разрешают программе открыть соединение с Telegram; сам номер и код "
    "передаются уже внутри этого соединения. У официальных клиентов такие "
    "ключи тоже есть, просто вшиты внутрь.\n\n"
    "Telegram выдаёт один ключ на номер, так что у вашего аккаунта будет свой.\n\n"
    "<b>Автоматически</b> — бот сам пройдёт my.telegram.org, от вас нужен "
    "только код от портала. Работает не всегда: портал часто отказывает "
    "запросам с серверов.\n"
    "<b>Руками</b> — если у вас ключи уже есть или автоматически не вышло."
)

MANUAL_KEYS_PROMPT = (
    "Пришлите api_id и api_hash одним сообщением, через пробел:\n\n"
    "<code>12345678 0123456789abcdef0123456789abcdef</code>\n\n"
    "Где взять: my.telegram.org → вход по номеру → API development tools → "
    "заполнить любые поля → Create application."
)

PORTAL_CODE_PROMPT = (
    "Придёт сообщение от служебного аккаунта Telegram с кодом для "
    "my.telegram.org — он выглядит как <code>3QvmDbabncs</code>.\n\n"
    "<b>Пришлите его сюда обычным сообщением.</b> Регистр букв важен.\n\n"
    "Этот код можно отправлять текстом: Telegram гасит только коды входа, а "
    "они состоят из цифр. Следующий код — как раз такой, и его нужно будет "
    "набрать кнопками."
)

CODE_PROMPT = (
    "Наберите код кнопками ниже и нажмите «Готово».\n\n"
    "<b>Не пересылайте и не отправляйте этот код сообщением</b> — Telegram "
    "гасит цифровые коды входа, отправленные внутри мессенджера, и он сразу "
    "станет недействительным."
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
    from tgparser.userbot.auth import normalize_phone

    phone = normalize_phone(message.text or "")
    if phone is None:
        await message.answer("Не похоже на номер. Пришлите в формате +79991234567.")
        return

    await state.update_data(phone=phone)
    await state.set_state(AuthFlow.keys)
    await message.answer(
        KEYS_PROMPT,
        reply_markup=keys_choice(ctx.app_settings.has_shared_keys),
    )


@router.callback_query(F.data == "keys:auto")
async def on_keys_auto(call: CallbackQuery, ctx: BotContext, state: FSMContext) -> None:
    phone = (await state.get_data()).get("phone")
    if not phone:
        await call.answer("Начните заново: нужен номер.", show_alert=True)
        return

    await call.message.edit_text("Запрашиваю код у my.telegram.org…")
    result = await ctx.auth.start_portal(call.from_user.id, phone)

    if result.outcome is Outcome.PORTAL_CODE_SENT:
        # Пад тут не нужен: код портала буквенно-цифровой, ждём сообщение.
        await state.set_state(AuthFlow.portal_code)
        await call.message.edit_text(
            PORTAL_CODE_PROMPT, reply_markup=back_to("menu:main")
        )
    else:
        await state.set_state(AuthFlow.keys)
        await call.message.edit_text(result.message, reply_markup=keys_retry())
    await call.answer()


@router.message(AuthFlow.portal_code)
async def on_portal_code(message: Message, ctx: BotContext, state: FSMContext) -> None:
    owner_id = message.from_user.id
    notice = await message.answer("Проверяю код и получаю ключи…")
    result = await ctx.auth.submit_portal_code(owner_id, message.text or "")

    if result.outcome is Outcome.CODE_SENT:
        await state.clear()
        pending = ctx.auth.get(owner_id)
        await notice.edit_text(
            f"{result.message}\n\n{CODE_PROMPT}",
            reply_markup=code_keypad(pending.masked if pending else ""),
        )
        return

    if result.outcome is Outcome.INVALID_CODE:
        await notice.edit_text(result.message)
        return

    if result.outcome is Outcome.PORTAL_FAILED:
        await state.set_state(AuthFlow.keys)
        await notice.edit_text(result.message, reply_markup=keys_retry())
        return

    await state.clear()
    await notice.edit_text(result.message, reply_markup=back_to("menu:main"))


@router.callback_query(F.data == "keys:manual")
async def on_keys_manual(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AuthFlow.manual_keys)
    await call.message.edit_text(MANUAL_KEYS_PROMPT, reply_markup=back_to("menu:main"))
    await call.answer()


@router.message(AuthFlow.manual_keys)
async def on_manual_keys(message: Message, ctx: BotContext, state: FSMContext) -> None:
    keys = parse_keys(message.text or "")
    if keys is None:
        await message.answer(
            "Не разобрал. Нужны число api_id и 32 символа api_hash, "
            "например: <code>12345678 0123456789abcdef0123456789abcdef</code>"
        )
        return

    phone = (await state.get_data()).get("phone")
    if not phone:
        await state.clear()
        await message.answer("Начните заново: нужен номер. /menu")
        return

    await _start_telegram(message, ctx, state, message.from_user.id, phone, keys)


@router.callback_query(F.data == "keys:shared")
async def on_keys_shared(call: CallbackQuery, ctx: BotContext, state: FSMContext) -> None:
    phone = (await state.get_data()).get("phone")
    if not phone:
        await call.answer("Начните заново: нужен номер.", show_alert=True)
        return
    await call.answer()
    await _start_telegram(call.message, ctx, state, call.from_user.id, phone, None)


async def _start_telegram(
    message: Message,
    ctx: BotContext,
    state: FSMContext,
    owner_id: int,
    phone: str,
    keys,
) -> None:
    result = await ctx.auth.start_telegram(owner_id, phone, keys)
    if result.outcome is not Outcome.CODE_SENT:
        await state.set_state(AuthFlow.keys)
        await message.answer(result.message, reply_markup=keys_retry())
        return

    await state.clear()
    pending = ctx.auth.get(owner_id)
    await message.answer(
        f"Telegram отправил код на аккаунт.\n\n{CODE_PROMPT}",
        reply_markup=code_keypad(pending.masked if pending else ""),
    )


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
    owner_id = call.from_user.id
    await ctx.auth.cancel(owner_id)
    await call.message.edit_text(
        "Вход отменён.",
        reply_markup=main_menu(
            await ctx.has_account(owner_id), ctx.scan.is_running(owner_id)
        ),
    )
    await call.answer()


@router.callback_query(F.data == "code:submit")
async def on_submit(call: CallbackQuery, ctx: BotContext, state: FSMContext) -> None:
    await call.answer("Проверяю…")
    owner_id = call.from_user.id
    result = await ctx.auth.submit_code(owner_id)

    if result.outcome is Outcome.SIGNED_IN:
        note = ""
        if result.keys is not None:
            note = f"\nСвои ключи приложения сохранены (api_id {result.keys.api_id})."
        await call.message.edit_text(
            f"{result.message}{note}\n\nМожно запускать обход.",
            reply_markup=main_menu(True, ctx.scan.is_running(owner_id)),
        )
        return

    if result.outcome is Outcome.CODE_SENT:
        pending = ctx.auth.get(owner_id)
        await call.message.edit_text(
            f"{result.message}\n\n{CODE_PROMPT}",
            reply_markup=code_keypad(pending.masked if pending else ""),
        )
        return

    if result.outcome is Outcome.NEEDS_PASSWORD:
        await state.set_state(AuthFlow.password)
        await call.message.edit_text(result.message)
        return

    if result.outcome is Outcome.INVALID_CODE:
        pending = ctx.auth.get(owner_id)
        await call.message.edit_text(
            f"{result.message}\n\n{CODE_PROMPT}",
            reply_markup=code_keypad(pending.masked if pending else ""),
        )
        return

    if result.outcome is Outcome.PORTAL_FAILED:
        await state.set_state(AuthFlow.keys)
        await call.message.edit_text(result.message, reply_markup=keys_retry())
        return

    await call.message.edit_text(result.message, reply_markup=back_to("menu:main"))


@router.message(AuthFlow.password)
async def on_password(message: Message, ctx: BotContext, state: FSMContext) -> None:
    password = message.text or ""
    # Пароль не должен оставаться в переписке.
    with contextlib.suppress(TelegramBadRequest):
        await message.delete()

    owner_id = message.from_user.id
    result = await ctx.auth.submit_password(owner_id, password)
    if result.outcome is Outcome.SIGNED_IN:
        await state.clear()
        await message.answer(
            f"{result.message}\n\nПароль удалил из чата. Можно запускать обход.",
            reply_markup=main_menu(True, ctx.scan.is_running(owner_id)),
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
        f"Ключи приложения: {'свои, api_id ' + str(account.api_id) if account.api_id else 'общие бота'}",
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
        "Аккаунт отключён, сессия удалена из базы. Собранные записи остались на месте.",
        reply_markup=main_menu(False, False),
    )
    await call.answer()


async def _refresh_keypad(call: CallbackQuery, masked: str) -> None:
    with contextlib.suppress(TelegramBadRequest):
        await call.message.edit_reply_markup(reply_markup=code_keypad(masked))
