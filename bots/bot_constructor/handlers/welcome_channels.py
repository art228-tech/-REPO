"""Каналы приветки: список разрешённых каналов + задержка у каждого."""
from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message,
)

from database import get_db
from handlers.start import is_admin
from states.fsm import BotSettingsStates

router = Router()


def _menu(bot_id: int, channels: list) -> InlineKeyboardMarkup:
    rows = []
    for ch in channels:
        rows.append([InlineKeyboardButton(
            text=f"\U0001F4E2 {ch['title'] or ch['chat_id']} \u2014 {ch['start_delay']} \u0441",
            callback_data=f"wchv:{ch['id']}")])
    rows.append([InlineKeyboardButton(text="\u2795 \u0414\u043e\u0431\u0430\u0432\u0438\u0442\u044c \u043a\u0430\u043d\u0430\u043b", callback_data=f"wch_add:{bot_id}")])
    rows.append([InlineKeyboardButton(text="\u00ab \u041d\u0430\u0437\u0430\u0434", callback_data=f"set:{bot_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data.startswith("wch:"))
async def cb_wch_list(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        await cb.answer("\u26d4", show_alert=True)
        return
    await state.clear()
    bot_id = int(cb.data.split(":")[1])
    chs = await get_db().list_welcome_channels(bot_id)
    await cb.message.edit_text(
        "<b>\U0001F4E2 \u041a\u0430\u043d\u0430\u043b\u044b \u043f\u0440\u0438\u0432\u0435\u0442\u043a\u0438</b>\n\n"
        f"\u0412\u0441\u0435\u0433\u043e: {len(chs)}\n\n"
        "\u041f\u0440\u0438\u0432\u0435\u0442\u043a\u0430 \u043e\u0442\u0432\u0435\u0447\u0430\u0435\u0442 \u0442\u043e\u043b\u044c\u043a\u043e \u043d\u0430 \u0437\u0430\u044f\u0432\u043a\u0438 \u0438\u0437 \u044d\u0442\u0438\u0445 \u043a\u0430\u043d\u0430\u043b\u043e\u0432. "
        "\u0423 \u043a\u0430\u0436\u0434\u043e\u0433\u043e \u2014 \u0441\u0432\u043e\u044f \u0437\u0430\u0434\u0435\u0440\u0436\u043a\u0430 \u0441\u0442\u0430\u0440\u0442\u0430 \u0441\u0446\u0435\u043d\u0430\u0440\u0438\u044f.\n"
        "<i>\u0415\u0441\u043b\u0438 \u0441\u043f\u0438\u0441\u043e\u043a \u043f\u0443\u0441\u0442 \u2014 \u043f\u0440\u0438\u0432\u0435\u0442\u043a\u0430 \u043d\u0435 \u043f\u0438\u0448\u0435\u0442 \u043d\u0438\u043a\u043e\u043c\u0443.</i>",
        reply_markup=_menu(bot_id, chs),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("wch_add:"))
async def cb_wch_add(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        return
    bot_id = int(cb.data.split(":")[1])
    await state.set_state(BotSettingsStates.wch_add_id)
    await state.update_data(wch_bot_id=bot_id)
    await cb.message.edit_text(
        "\u041f\u0440\u0438\u0448\u043b\u0438 <b>chat_id \u043a\u0430\u043d\u0430\u043b\u0430</b> (\u043e\u0442\u0440\u0438\u0446\u0430\u0442\u0435\u043b\u044c\u043d\u043e\u0435 \u0447\u0438\u0441\u043b\u043e), "
        "\u0432 \u043a\u043e\u0442\u043e\u0440\u043e\u043c \u043f\u0440\u0438\u0432\u0435\u0442\u043a\u0430 \u0434\u043e\u043b\u0436\u043d\u0430 \u0440\u0430\u0431\u043e\u0442\u0430\u0442\u044c."
    )
    await cb.answer()


@router.message(BotSettingsStates.wch_add_id)
async def m_wch_add(message: Message, state: FSMContext, bot: Bot) -> None:
    if not is_admin(message.from_user.id):
        return
    try:
        chat_id = int((message.text or "").strip())
    except ValueError:
        await message.answer("\u041d\u0443\u0436\u043d\u043e \u0446\u0435\u043b\u043e\u0435 \u0447\u0438\u0441\u043b\u043e (chat_id \u043a\u0430\u043d\u0430\u043b\u0430).")
        return
    data = await state.get_data()
    bot_id = data["wch_bot_id"]
    title = str(chat_id)
    try:
        chat = await bot.get_chat(chat_id)
        title = chat.title or title
    except Exception:
        pass
    await get_db().add_welcome_channel(bot_id, chat_id, title)
    await state.clear()
    chs = await get_db().list_welcome_channels(bot_id)
    await message.answer(
        f"\u2705 \u041a\u0430\u043d\u0430\u043b \u00ab{title}\u00bb \u0434\u043e\u0431\u0430\u0432\u043b\u0435\u043d.",
        reply_markup=_menu(bot_id, chs),
    )


@router.callback_query(F.data.startswith("wchv:"))
async def cb_wch_view(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        return
    wch_id = int(cb.data.split(":")[1])
    ch = await get_db().get_welcome_channel(wch_id)
    if not ch:
        await cb.answer("\u041d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d\u043e", show_alert=True)
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="\u23f1 \u0417\u0430\u0434\u0435\u0440\u0436\u043a\u0430 \u0441\u0442\u0430\u0440\u0442\u0430", callback_data=f"wch_delay:{wch_id}")],
        [InlineKeyboardButton(text="\U0001F5d1 \u0423\u0434\u0430\u043b\u0438\u0442\u044c \u043a\u0430\u043d\u0430\u043b", callback_data=f"wch_del:{wch_id}")],
        [InlineKeyboardButton(text="\u00ab \u041a \u043a\u0430\u043d\u0430\u043b\u0430\u043c", callback_data=f"wch:{ch['bot_id']}")],
    ])
    await cb.message.edit_text(
        f"<b>\U0001F4E2 {ch['title']}</b>\n\n"
        f"chat_id: <code>{ch['chat_id']}</code>\n"
        f"\u0417\u0430\u0434\u0435\u0440\u0436\u043a\u0430 \u0441\u0442\u0430\u0440\u0442\u0430: <b>{ch['start_delay']} \u0441</b>",
        reply_markup=kb,
    )
    await cb.answer()


@router.callback_query(F.data.startswith("wch_delay:"))
async def cb_wch_delay(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        return
    wch_id = int(cb.data.split(":")[1])
    await state.set_state(BotSettingsStates.wch_set_delay)
    await state.update_data(wch_id=wch_id)
    await cb.message.edit_text(
        "\u041f\u0440\u0438\u0448\u043b\u0438 <b>\u0437\u0430\u0434\u0435\u0440\u0436\u043a\u0443 \u0441\u0442\u0430\u0440\u0442\u0430</b> \u0441\u0446\u0435\u043d\u0430\u0440\u0438\u044f \u0434\u043b\u044f \u044d\u0442\u043e\u0433\u043e \u043a\u0430\u043d\u0430\u043b\u0430 "
        "\u0432 \u0441\u0435\u043a\u0443\u043d\u0434\u0430\u0445 (0 \u2014 \u0441\u0440\u0430\u0437\u0443)."
    )
    await cb.answer()


@router.message(BotSettingsStates.wch_set_delay)
async def m_wch_delay(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return
    try:
        v = int((message.text or "").strip())
        if v < 0:
            raise ValueError
    except ValueError:
        await message.answer("\u041d\u0443\u0436\u043d\u043e \u0446\u0435\u043b\u043e\u0435 \u0447\u0438\u0441\u043b\u043e (0 \u0438\u043b\u0438 \u0431\u043e\u043b\u044c\u0448\u0435).")
        return
    data = await state.get_data()
    wch_id = data["wch_id"]
    await get_db().set_welcome_channel_delay(wch_id, v)
    ch = await get_db().get_welcome_channel(wch_id)
    await state.clear()
    chs = await get_db().list_welcome_channels(ch["bot_id"])
    await message.answer(
        f"\u2705 \u0417\u0430\u0434\u0435\u0440\u0436\u043a\u0430 \u043a\u0430\u043d\u0430\u043b\u0430 \u00ab{ch['title']}\u00bb: {v} \u0441.",
        reply_markup=_menu(ch["bot_id"], chs),
    )


@router.callback_query(F.data.startswith("wch_del:"))
async def cb_wch_del(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        return
    wch_id = int(cb.data.split(":")[1])
    ch = await get_db().get_welcome_channel(wch_id)
    if not ch:
        await cb.answer("\u041d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d\u043e", show_alert=True)
        return
    bot_id = ch["bot_id"]
    await get_db().delete_welcome_channel(wch_id)
    chs = await get_db().list_welcome_channels(bot_id)
    await cb.message.edit_text(
        "\U0001F5d1 \u041a\u0430\u043d\u0430\u043b \u0443\u0434\u0430\u043b\u0451\u043d.",
        reply_markup=_menu(bot_id, chs),
    )
    await cb.answer()
