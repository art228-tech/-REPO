"""Меню конкретной приветки: настройки, удаление."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bots.manager import get_manager
from database import get_db
from handlers.start import is_admin
from keyboards.constructor_kb import (
    back_to,
    bot_menu,
    bots_list,
    settings_menu,
    yes_no,
)
from states.fsm import BotSettingsStates

router = Router(name="bot_menu")


@router.callback_query(F.data.startswith("bot:"))
async def cb_open_bot(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        await cb.answer("⛔", show_alert=True)
        return
    await state.clear()
    bot_id = int(cb.data.split(":")[1])
    db = get_db()
    b = await db.get_greeting_bot(bot_id)
    if not b:
        await cb.answer("Приветка не найдена", show_alert=True)
        return
    steps = await db.list_steps(bot_id)
    users = await db.list_users(bot_id)
    text = (
        f"<b>🤖 @{b['username']}</b>\n"
        f"{b['name'] or ''}\n\n"
        f"📜 Шагов в сценарии: <b>{len(steps)}</b>\n"
        f"👥 Пользователей: <b>{len(users)}</b>\n"
        f"⏱ Задержка старта: <b>{b['join_delay']} с</b>\n"
        f"🗑 Таймер удаления: <b>{b['delete_timer']} с</b>\n"
        f"✍️ Вид: <b>{'с имитацией печати' if b['typing_mode'] else 'обычная'}</b>\n"
    )
    await cb.message.edit_text(text, reply_markup=bot_menu(bot_id))
    await cb.answer()


@router.callback_query(F.data.startswith("set:"))
async def cb_settings(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        await cb.answer("⛔", show_alert=True)
        return
    await state.clear()
    bot_id = int(cb.data.split(":")[1])
    b = await get_db().get_greeting_bot(bot_id)
    if not b:
        await cb.answer("Не найдено", show_alert=True)
        return
    await cb.message.edit_text(
        "<b>⚙️ Настройки приветки</b>\n\n"
        "• <b>Задержка перед стартом</b> — сколько секунд ждать, "
        "прежде чем приветка начнёт писать новому юзеру.\n"
        "• <b>Таймер удаления старых</b> — через сколько секунд "
        "удалить старое сообщение (после перехода к следующему шагу).",
        reply_markup=settings_menu(bot_id, b["join_delay"], b["delete_timer"], b["typing_mode"]),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("set_jd:"))
async def cb_set_jd(cb: CallbackQuery, state: FSMContext) -> None:
    bot_id = int(cb.data.split(":")[1])
    await state.set_state(BotSettingsStates.join_delay)
    await state.update_data(bot_id=bot_id)
    await cb.message.edit_text(
        "Пришли число секунд (целое, ≥ 0) — задержка перед началом сценария после "
        "подачи заявки или /start.",
        reply_markup=back_to(f"set:{bot_id}", "❌ Отмена"),
    )
    await cb.answer()


@router.message(BotSettingsStates.join_delay)
async def msg_set_jd(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return
    try:
        v = int(message.text.strip())
        if v < 0 or v > 86400:
            raise ValueError
    except (ValueError, AttributeError):
        await message.answer("Нужно целое число от 0 до 86400. Попробуй ещё раз.")
        return
    data = await state.get_data()
    bot_id = int(data["bot_id"])
    await get_db().update_greeting_bot_settings(bot_id, join_delay=v)
    await state.clear()
    b = await get_db().get_greeting_bot(bot_id)
    await message.answer(
        f"✅ Задержка обновлена: <b>{v} с</b>",
        reply_markup=settings_menu(bot_id, b["join_delay"], b["delete_timer"], b["typing_mode"]),
    )


@router.callback_query(F.data.startswith("set_dt:"))
async def cb_set_dt(cb: CallbackQuery, state: FSMContext) -> None:
    bot_id = int(cb.data.split(":")[1])
    await state.set_state(BotSettingsStates.delete_timer)
    await state.update_data(bot_id=bot_id)
    await cb.message.edit_text(
        "Пришли число секунд (целое, ≥ 1) — через сколько удалять старое сообщение.",
        reply_markup=back_to(f"set:{bot_id}", "❌ Отмена"),
    )
    await cb.answer()


@router.message(BotSettingsStates.delete_timer)
async def msg_set_dt(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return
    try:
        v = int(message.text.strip())
        if v < 1 or v > 86400:
            raise ValueError
    except (ValueError, AttributeError):
        await message.answer("Нужно целое число от 1 до 86400. Попробуй ещё раз.")
        return
    data = await state.get_data()
    bot_id = int(data["bot_id"])
    await get_db().update_greeting_bot_settings(bot_id, delete_timer=v)
    await state.clear()
    b = await get_db().get_greeting_bot(bot_id)
    await message.answer(
        f"✅ Таймер удаления обновлён: <b>{v} с</b>",
        reply_markup=settings_menu(bot_id, b["join_delay"], b["delete_timer"], b["typing_mode"]),
    )


@router.callback_query(F.data.startswith("delbot:"))
async def cb_delbot(cb: CallbackQuery) -> None:
    if not is_admin(cb.from_user.id):
        await cb.answer("⛔", show_alert=True)
        return
    bot_id = int(cb.data.split(":")[1])
    b = await get_db().get_greeting_bot(bot_id)
    if not b:
        await cb.answer("Не найдено", show_alert=True)
        return
    await cb.message.edit_text(
        f"⚠️ Удалить приветку <b>@{b['username']}</b>?\n\n"
        f"Это удалит всё: пользователей, сценарий, статистику, реф-ссылки.\n"
        f"Восстановить будет нельзя.",
        reply_markup=yes_no(f"delbot_yes:{bot_id}", f"bot:{bot_id}"),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("delbot_yes:"))
async def cb_delbot_yes(cb: CallbackQuery) -> None:
    if not is_admin(cb.from_user.id):
        await cb.answer("⛔", show_alert=True)
        return
    bot_id = int(cb.data.split(":")[1])
    await get_manager().stop_bot(bot_id)
    await get_db().delete_greeting_bot(bot_id)
    bots = await get_db().list_greeting_bots()
    await cb.message.edit_text("✅ Приветка удалена.", reply_markup=bots_list(bots))
    await cb.answer()



@router.callback_query(F.data.startswith("set_tm:"))
async def cb_toggle_typing_mode(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        await cb.answer("\u26d4", show_alert=True)
        return
    bot_id = int(cb.data.split(":")[1])
    db = get_db()
    b = await db.get_greeting_bot(bot_id)
    new_mode = 0 if b["typing_mode"] else 1
    await db.update_greeting_bot_settings(bot_id, typing_mode=new_mode)
    b = await db.get_greeting_bot(bot_id)
    from keyboards.constructor_kb import settings_menu
    await cb.message.edit_reply_markup(
        reply_markup=settings_menu(bot_id, b["join_delay"], b["delete_timer"], b["typing_mode"])
    )
    await cb.answer("Вид: " + ("с имитацией печати" if new_mode else "обычная"))
