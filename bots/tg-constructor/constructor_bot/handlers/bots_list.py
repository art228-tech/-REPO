"""
View and manage the list of added welcome bots.
"""
from aiogram import Router, F
from aiogram.types import CallbackQuery
from sqlalchemy import select

from shared.db import db
from shared.models import WelcomeBot
from constructor_bot.keyboards.menus import bots_list_kb, bot_menu_kb, confirm_delete_kb

router = Router()


@router.callback_query(F.data == "bots_list")
async def cb_bots_list(callback: CallbackQuery):
    async with db() as session:
        result = await session.execute(select(WelcomeBot).order_by(WelcomeBot.id))
        bots = result.scalars().all()

    if not bots:
        text = "📭 У вас пока нет добавленных ботов."
    else:
        text = f"🤖 <b>Ваши боты</b> ({len(bots)} шт.):"

    await callback.message.edit_text(text, reply_markup=bots_list_kb(bots))
    await callback.answer()


@router.callback_query(F.data.startswith("bot_menu:"))
async def cb_bot_menu(callback: CallbackQuery):
    bot_id = int(callback.data.split(":")[1])
    async with db() as session:
        bot = await session.get(WelcomeBot, bot_id)

    if not bot:
        await callback.answer("Бот не найден.", show_alert=True)
        return

    status = "✅ Активен" if bot.is_active else "⏸ На паузе"
    text = (
        f"🤖 <b>{bot.name}</b>\n"
        f"👤 @{bot.username or 'неизвестно'}\n"
        f"📊 Статус: {status}\n"
        f"⏱ Задержка первого сообщения: {bot.delay_seconds} сек\n"
        f"🔔 Напоминание при зависании: {bot.reminder_seconds} сек\n"
    )
    await callback.message.edit_text(text, reply_markup=bot_menu_kb(bot_id))
    await callback.answer()


@router.callback_query(F.data.startswith("toggle_bot:"))
async def cb_toggle_bot(callback: CallbackQuery):
    bot_id = int(callback.data.split(":")[1])
    async with db() as session:
        bot = await session.get(WelcomeBot, bot_id)
        if bot:
            bot.is_active = not bot.is_active
    await callback.answer(f"{'▶️ Запущен' if bot.is_active else '⏸ Поставлен на паузу'}")
    # Refresh menu
    await cb_bot_menu(callback)


@router.callback_query(F.data.startswith("delete_bot:"))
async def cb_delete_bot_confirm(callback: CallbackQuery):
    bot_id = int(callback.data.split(":")[1])
    await callback.message.edit_text(
        "⚠️ Вы уверены, что хотите удалить бота?\nВсе данные (пользователи, сценарий) будут удалены безвозвратно.",
        reply_markup=confirm_delete_kb(
            confirm_cb=f"confirm_delete_bot:{bot_id}",
            cancel_cb=f"bot_menu:{bot_id}"
        )
    )
    await callback.answer()


@router.callback_query(F.data.startswith("confirm_delete_bot:"))
async def cb_delete_bot(callback: CallbackQuery):
    bot_id = int(callback.data.split(":")[1])
    async with db() as session:
        bot = await session.get(WelcomeBot, bot_id)
        if bot:
            await session.delete(bot)
    await callback.answer("🗑 Бот удалён.")

    # Refresh list
    async with db() as session:
        result = await session.execute(select(WelcomeBot).order_by(WelcomeBot.id))
        bots = result.scalars().all()
    text = f"🤖 <b>Ваши боты</b> ({len(bots)} шт.):" if bots else "📭 У вас пока нет добавленных ботов."
    await callback.message.edit_text(text, reply_markup=bots_list_kb(bots))
