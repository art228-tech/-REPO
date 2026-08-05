"""Управление помощниками."""
from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramUnauthorizedError
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from database import get_db
from handlers.common import is_admin
from keyboards.kb import helpers_menu, helper_card
from states.fsm import HelperStates
from utils.manager import get_manager

router = Router()


@router.callback_query(F.data == "helpers")
async def cb_helpers(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        await cb.answer("⛔", show_alert=True)
        return
    await state.clear()
    hs = await get_db().list_helpers()
    await cb.message.edit_text(
        f"<b>🤖 Помощники</b>\n\nВсего: {len(hs)}\n"
        "🟢 — работает, 💀 — заморожен/удалён",
        reply_markup=helpers_menu(hs),
    )
    await cb.answer()


@router.callback_query(F.data == "h_add")
async def cb_h_add(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        return
    await state.set_state(HelperStates.wait_token)
    await cb.message.edit_text(
        "<b>➕ Добавить помощника</b>\n\n"
        "Пришли <b>токен</b> бота-помощника (формат <code>1234:AA...</code>).\n\n"
        "Помощник должен быть админом нужного канала с правом "
        "<b>«Добавлять участников»</b>."
    )
    await cb.answer()


@router.message(HelperStates.wait_token)
async def m_h_token(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return
    token = (message.text or "").strip()
    if ":" not in token or len(token) < 30:
        await message.answer("Не похоже на токен. Жду <code>1234567:AA...</code>")
        return
    db = get_db()
    if await db.get_helper_by_token(token):
        await message.answer("Этот помощник уже добавлен.")
        return
    try:
        b = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        me = await b.get_me()
        await b.session.close()
    except TelegramUnauthorizedError:
        await message.answer("Токен невалиден (Unauthorized).")
        return
    except Exception as e:
        await message.answer(f"Ошибка проверки токена: {e}")
        return

    helper_id = await db.add_helper(token, me.id, me.username, me.first_name)
    await state.clear()
    await get_manager().start_one(helper_id, token)

    hs = await db.list_helpers()
    await message.answer(
        f"✅ Помощник <b>@{me.username}</b> добавлен и запущен.\n"
        "Теперь добавь его админом канала с правом "
        "<b>«Добавлять участников»</b>, потом привяжи канал в разделе «Каналы».",
        reply_markup=helpers_menu(hs),
    )


@router.callback_query(F.data.startswith("h:"))
async def cb_h_card(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        return
    h_id = int(cb.data.split(":")[1])
    h = await get_db().get_helper(h_id)
    if not h:
        await cb.answer("Не найден", show_alert=True)
        return
    chs = await get_db().list_channels(h_id)
    status = "🟢 работает" if h["is_alive"] else "💀 заморожен/удалён"
    err = f"\n<i>Ошибка: {h['last_error'][:200]}</i>" if h["last_error"] else ""
    await cb.message.edit_text(
        f"<b>🤖 {h['name']}</b> (@{h['username']})\n"
        f"id: <code>{h['tg_id']}</code>\n"
        f"Статус: {status}\n"
        f"Каналов: {len(chs)}{err}",
        reply_markup=helper_card(h_id),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("h_del:"))
async def cb_h_del(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        return
    h_id = int(cb.data.split(":")[1])
    await get_manager().stop_one(h_id)
    await get_db().delete_helper(h_id)
    hs = await get_db().list_helpers()
    await cb.message.edit_text("🗑 Помощник удалён.", reply_markup=helpers_menu(hs))
    await cb.answer()
