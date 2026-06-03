"""
Хендлеры приветочного бота (greeting bot).

Каждая приветка получает свой Dispatcher с этими handlers.
"""
from __future__ import annotations

import logging

from aiogram import Bot, Dispatcher, F
from aiogram.exceptions import TelegramForbiddenError
from aiogram.filters import CommandStart, CommandObject
from aiogram.types import (
    CallbackQuery,
    ChatJoinRequest,
    Message,
)

from database import get_db
from bots.scenario import get_engine

log = logging.getLogger("greeter")


def register_greeter_handlers(dp: Dispatcher, bot_record_id: int) -> None:
    """Регистрирует хендлеры приветочного бота."""

    async def _get_bot_record():
        return await get_db().get_greeting_bot(bot_record_id)

    @dp.message(CommandStart())
    async def on_start(message: Message, command: CommandObject) -> None:
        db = get_db()
        bot_record = await _get_bot_record()
        if not bot_record:
            return
        # Парсим deep link: реферальная ссылка вида /start ref_<code>
        ref_link_id = None
        if command.args:
            args = command.args.strip()
            if args.startswith("ref_"):
                code = args[4:]
                ref_row = await db.get_ref_link_by_code(bot_record["id"], code)
                if ref_row:
                    ref_link_id = ref_row["id"]
        # Сохраняем пользователя
        user = await db.upsert_user(
            bot_record["id"],
            message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
            is_premium=bool(getattr(message.from_user, "is_premium", False)),
            ref_link_id=ref_link_id,
        )
        # Запускаем (или перезапускаем) сценарий
        engine = get_engine()
        await engine.start_or_restart(message.bot, bot_record, user)

    @dp.chat_join_request()
    async def on_join_request(req: ChatJoinRequest) -> None:
        db = get_db()
        bot_record = await _get_bot_record()
        if not bot_record:
            return
        user = await db.upsert_user(
            bot_record["id"],
            req.from_user.id,
            username=req.from_user.username,
            first_name=req.from_user.first_name,
            is_premium=bool(getattr(req.from_user, "is_premium", False)),
        )
        # По умолчанию заявку не одобряем (это решает админ канала или другие боты)
        engine = get_engine()
        try:
            await engine.start_or_restart(req.bot, bot_record, user)
        except Exception as e:
            log.exception("join_request scenario error: %s", e)

    @dp.callback_query(F.data.startswith("op_check:"))
    async def on_op_check(cb: CallbackQuery) -> None:
        db = get_db()
        bot_record = await _get_bot_record()
        if not bot_record:
            await cb.answer()
            return
        user = await db.get_user_by_tg(bot_record["id"], cb.from_user.id)
        if not user:
            await cb.answer("Сначала нажми /start", show_alert=True)
            return
        engine = get_engine()
        advance, alert = await engine.handle_callback(
            cb.bot, bot_record, user["id"], "check_op", {}
        )
        if not advance:
            await cb.answer(alert or "❌ Не все подписки выполнены", show_alert=True)
            return
        await cb.answer(alert or "✅ Готово")
        # Записываем прохождение
        step = await db.get_step_by_order(bot_record["id"], user["current_step_order"])
        if step:
            await db.record_step_completion(user["id"], step["id"])
        await engine.advance(cb.bot, bot_record, user["id"])

    @dp.message(F.web_app_data)
    async def on_web_app_data(message: Message) -> None:
        # На случай если webapp вернёт данные через reply keyboard
        db = get_db()
        bot_record = await _get_bot_record()
        if not bot_record:
            return
        user = await db.get_user_by_tg(bot_record["id"], message.from_user.id)
        if not user:
            return
        data = message.web_app_data.data if message.web_app_data else ""
        if data == "roulette_done":
            engine = get_engine()
            await engine.handle_roulette_done(
                message.bot, bot_record, message.from_user.id, 5000
            )

    @dp.message()
    async def on_any_message(message: Message) -> None:
        db = get_db()
        bot_record = await _get_bot_record()
        if not bot_record:
            return
        user = await db.get_user_by_tg(bot_record["id"], message.from_user.id)
        if not user:
            # Пользователь пишет, не нажав старт — упрощаем: считаем за старт
            user = await db.upsert_user(
                bot_record["id"],
                message.from_user.id,
                username=message.from_user.username,
                first_name=message.from_user.first_name,
                is_premium=bool(getattr(message.from_user, "is_premium", False)),
            )
            engine = get_engine()
            await engine.start_or_restart(message.bot, bot_record, user)
            return
        engine = get_engine()
        # Если шаг ждёт сообщения от юзера — продвигаем
        advanced = await engine.handle_message_from_user(
            message.bot, bot_record, user["id"], message.text or ""
        )
        if advanced:
            return
        # Иначе игнорируем
