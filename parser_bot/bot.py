"""Интерфейс управляющего бота (aiogram 3)."""
from __future__ import annotations

import html
import logging

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from .config import Config
from .crawler import Crawler
from .database import STATUS_TITLES, Database
from .userbot import LoginError, UserBot

log = logging.getLogger(__name__)

PAGE_SIZE = 20

# Базы, которые показываем в разделе "Базы".
VISIBLE_STATUSES = [
    "unrestricted",
    "captcha",
    "op_checked",
    "op_unchecked",
    "small",
    "queue",
    "error",
]


class LoginStates(StatesGroup):
    session = State()
    phone = State()
    code = State()
    password = State()


class SeedStates(StatesGroup):
    waiting = State()


def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="👤 Вход по сессии", callback_data="login_session"),
                InlineKeyboardButton(text="📱 Вход по номеру", callback_data="login_phone"),
            ],
            [InlineKeyboardButton(text="🔗 Добавить чат(ы)", callback_data="add_seed")],
            [
                InlineKeyboardButton(text="▶️ Старт", callback_data="start"),
                InlineKeyboardButton(text="⏹ Стоп", callback_data="stop"),
            ],
            [InlineKeyboardButton(text="🔁 Перепроверить «без ограничений»",
                                  callback_data="recheck")],
            [
                InlineKeyboardButton(text="🗂 Базы", callback_data="bases"),
                InlineKeyboardButton(text="ℹ️ Статус", callback_data="status"),
            ],
        ]
    )


def build_dispatcher(cfg: Config, db: Database, userbot: UserBot, crawler: Crawler) -> Dispatcher:
    dp = Dispatcher()
    router = Router()
    dp.include_router(router)

    def is_admin(uid: int | None) -> bool:
        return uid == cfg.admin_id

    # ---------- /start ----------
    @router.message(Command("start", "menu"))
    async def cmd_start(message: Message, state: FSMContext):
        if not is_admin(message.from_user.id):
            return
        await state.clear()
        await message.answer(
            "🤖 <b>Парсер чатов</b>\n\n"
            "1. Войдите в аккаунт (сессия или номер).\n"
            "2. Пришлите ссылку(и) на чат.\n"
            "3. Запустите парсинг.\n\n"
            "Бот ставит точку в чат и определяет: капча / обязательная подписка (ОП) / "
            "без ограничений (от "
            f"{cfg.min_members} участников).",
            reply_markup=main_menu(),
        )

    # ---------- статус ----------
    async def status_text() -> str:
        counts = await db.count_by_status()
        authorized = await userbot.is_authorized()
        acc = await userbot.account_name() if authorized else "—"
        running = crawler.running
        lines = [
            f"👤 Аккаунт: <b>{html.escape(acc)}</b>",
            f"⚙️ Парсинг: <b>{'идёт (' + (crawler.mode or '') + ')' if running else 'остановлен'}</b>",
            "",
            "<b>Базы:</b>",
        ]
        for st in VISIBLE_STATUSES:
            lines.append(f"• {STATUS_TITLES.get(st, st)}: <b>{counts.get(st, 0)}</b>")
        return "\n".join(lines)

    @router.callback_query(F.data == "status")
    async def cb_status(call: CallbackQuery):
        if not is_admin(call.from_user.id):
            return
        await call.message.answer(await status_text(), reply_markup=main_menu())
        await call.answer()

    # ---------- вход по сессии ----------
    @router.callback_query(F.data == "login_session")
    async def cb_login_session(call: CallbackQuery, state: FSMContext):
        if not is_admin(call.from_user.id):
            return
        await state.set_state(LoginStates.session)
        await call.message.answer(
            "Пришлите <b>строку сессии</b> (StringSession) аккаунта Telegram."
        )
        await call.answer()

    @router.message(LoginStates.session)
    async def on_session(message: Message, state: FSMContext):
        if not is_admin(message.from_user.id):
            return
        await state.clear()
        try:
            name = await userbot.login_with_session(message.text.strip())
        except LoginError as e:
            await message.answer(f"❌ {e}", reply_markup=main_menu())
            return
        await message.answer(f"✅ Вошёл в аккаунт: <b>{html.escape(name)}</b>",
                             reply_markup=main_menu())

    # ---------- вход по номеру ----------
    @router.callback_query(F.data == "login_phone")
    async def cb_login_phone(call: CallbackQuery, state: FSMContext):
        if not is_admin(call.from_user.id):
            return
        await state.set_state(LoginStates.phone)
        await call.message.answer("Пришлите номер телефона в формате <code>+79991234567</code>.")
        await call.answer()

    @router.message(LoginStates.phone)
    async def on_phone(message: Message, state: FSMContext):
        if not is_admin(message.from_user.id):
            return
        phone = message.text.strip()
        try:
            await userbot.start_phone_login(phone)
        except LoginError as e:
            await state.clear()
            await message.answer(f"❌ {e}", reply_markup=main_menu())
            return
        await state.set_state(LoginStates.code)
        await message.answer(
            "Код выслан в Telegram. Пришлите его <b>с пробелами между цифрами</b> "
            "(например <code>1 2 3 4 5</code>), чтобы Telegram не аннулировал код."
        )

    @router.message(LoginStates.code)
    async def on_code(message: Message, state: FSMContext):
        if not is_admin(message.from_user.id):
            return
        code = message.text.replace(" ", "").strip()
        try:
            name = await userbot.submit_code(code)
        except LoginError as e:
            if str(e) == "2FA":
                await state.set_state(LoginStates.password)
                await message.answer("Включён облачный пароль (2FA). Пришлите пароль.")
                return
            await state.clear()
            await message.answer(f"❌ {e}", reply_markup=main_menu())
            return
        await state.clear()
        await message.answer(f"✅ Вошёл в аккаунт: <b>{html.escape(name or '?')}</b>",
                             reply_markup=main_menu())

    @router.message(LoginStates.password)
    async def on_password(message: Message, state: FSMContext):
        if not is_admin(message.from_user.id):
            return
        try:
            name = await userbot.submit_password(message.text.strip())
        except LoginError as e:
            await state.clear()
            await message.answer(f"❌ {e}", reply_markup=main_menu())
            return
        await state.clear()
        await message.answer(f"✅ Вошёл в аккаунт: <b>{html.escape(name)}</b>",
                             reply_markup=main_menu())

    # ---------- добавить сид ----------
    @router.callback_query(F.data == "add_seed")
    async def cb_add_seed(call: CallbackQuery, state: FSMContext):
        if not is_admin(call.from_user.id):
            return
        await state.set_state(SeedStates.waiting)
        await call.message.answer(
            "Пришлите одну или несколько ссылок на чаты (каждая с новой строки).\n"
            "Поддерживаю @username, t.me/username, t.me/+invite."
        )
        await call.answer()

    @router.message(SeedStates.waiting)
    async def on_seed(message: Message, state: FSMContext):
        if not is_admin(message.from_user.id):
            return
        await state.clear()
        added, skipped = 0, 0
        for line in message.text.splitlines():
            line = line.strip()
            if not line:
                continue
            if await crawler.add_seed(line):
                added += 1
            else:
                skipped += 1
        await message.answer(
            f"Добавлено новых: <b>{added}</b>, пропущено/дубликаты: <b>{skipped}</b>.\n"
            "Нажмите ▶️ Старт, чтобы запустить парсинг.",
            reply_markup=main_menu(),
        )

    # ---------- старт / стоп / перепроверка ----------
    @router.callback_query(F.data == "start")
    async def cb_start(call: CallbackQuery):
        if not is_admin(call.from_user.id):
            return
        msg = await crawler.start()
        await call.message.answer(msg, reply_markup=main_menu())
        await call.answer()

    @router.callback_query(F.data == "stop")
    async def cb_stop(call: CallbackQuery):
        if not is_admin(call.from_user.id):
            return
        msg = await crawler.stop()
        await call.message.answer(msg, reply_markup=main_menu())
        await call.answer()

    @router.callback_query(F.data == "recheck")
    async def cb_recheck(call: CallbackQuery):
        if not is_admin(call.from_user.id):
            return
        msg = await crawler.start_recheck()
        await call.message.answer(msg, reply_markup=main_menu())
        await call.answer()

    # ---------- базы ----------
    def bases_menu() -> InlineKeyboardMarkup:
        rows = [
            [InlineKeyboardButton(text=STATUS_TITLES.get(st, st),
                                  callback_data=f"list:{st}:0")]
            for st in VISIBLE_STATUSES
        ]
        rows.append([InlineKeyboardButton(text="⬅️ Меню", callback_data="menu")])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    @router.callback_query(F.data == "bases")
    async def cb_bases(call: CallbackQuery):
        if not is_admin(call.from_user.id):
            return
        counts = await db.count_by_status()
        rows = [
            [InlineKeyboardButton(
                text=f"{STATUS_TITLES.get(st, st)} ({counts.get(st, 0)})",
                callback_data=f"list:{st}:0")]
            for st in VISIBLE_STATUSES
        ]
        rows.append([InlineKeyboardButton(text="⬅️ Меню", callback_data="menu")])
        await call.message.answer("Выберите базу:",
                                  reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
        await call.answer()

    @router.callback_query(F.data == "menu")
    async def cb_menu(call: CallbackQuery):
        if not is_admin(call.from_user.id):
            return
        await call.message.answer("Меню:", reply_markup=main_menu())
        await call.answer()

    @router.callback_query(F.data.startswith("list:"))
    async def cb_list(call: CallbackQuery):
        if not is_admin(call.from_user.id):
            return
        _, status, offset_s = call.data.split(":")
        offset = int(offset_s)
        rows = await db.list_by_status(status, limit=PAGE_SIZE, offset=offset)
        counts = await db.count_by_status()
        total = counts.get(status, 0)
        title = STATUS_TITLES.get(status, status)
        if not rows:
            await call.message.answer(f"База «{title}» пуста.", reply_markup=bases_menu())
            await call.answer()
            return
        lines = [f"<b>{title}</b> — всего {total}\n"]
        for i, r in enumerate(rows, start=offset + 1):
            name = html.escape(r["title"] or r["ident"])
            link = r["link"] or ""
            members = r["members"] or 0
            if link:
                lines.append(f"{i}. <a href=\"{html.escape(link)}\">{name}</a> — {members} уч.")
            else:
                lines.append(f"{i}. {name} — {members} уч.")

        nav: list[InlineKeyboardButton] = []
        if offset > 0:
            nav.append(InlineKeyboardButton(
                text="⬅️ Назад", callback_data=f"list:{status}:{max(0, offset - PAGE_SIZE)}"))
        if offset + PAGE_SIZE < total:
            nav.append(InlineKeyboardButton(
                text="Вперёд ➡️", callback_data=f"list:{status}:{offset + PAGE_SIZE}"))
        kb_rows = []
        if nav:
            kb_rows.append(nav)
        kb_rows.append([InlineKeyboardButton(text="🗂 К базам", callback_data="bases")])
        await call.message.answer(
            "\n".join(lines),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows),
            disable_web_page_preview=True,
        )
        await call.answer()

    # ---------- фолбэк: чтобы бот всегда отвечал ----------
    @router.message()
    async def fallback(message: Message, state: FSMContext):
        if not is_admin(message.from_user.id):
            await message.answer(
                "⛔ Доступ только для администратора.\n"
                f"Ваш Telegram id: <code>{message.from_user.id}</code>\n"
                f"(в настройках разрешён id: <code>{cfg.admin_id}</code>)"
            )
            return
        await state.clear()
        await message.answer("Не понял команду. Открываю меню:", reply_markup=main_menu())

    return dp
