"""
Менеджер приветочных ботов.

Запускает Bot + Dispatcher для каждой приветки в отдельной asyncio задаче.
Поддерживает динамическое добавление и удаление ботов.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramUnauthorizedError

from database import get_db
from bots.greeter import register_greeter_handlers

log = logging.getLogger("manager")


class BotManager:
    def __init__(self) -> None:
        # bot_record_id -> (Bot, Dispatcher, Task)
        self._bots: dict[int, tuple[Bot, Dispatcher, asyncio.Task]] = {}
        self._lock = asyncio.Lock()

    async def start_all(self) -> None:
        """Загружает всех ботов из БД и запускает их поллинг."""
        db = get_db()
        rows = await db.list_greeting_bots()
        for r in rows:
            if r["is_active"]:
                try:
                    await self.start_bot(r["id"], r["token"])
                except Exception as e:
                    log.error("Не удалось запустить приветку %s: %s", r["id"], e)

    async def start_bot(self, bot_record_id: int, token: str) -> Bot:
        async with self._lock:
            if bot_record_id in self._bots:
                return self._bots[bot_record_id][0]

            bot = Bot(
                token=token,
                default=DefaultBotProperties(parse_mode=ParseMode.HTML),
            )
            dp = Dispatcher()
            register_greeter_handlers(dp, bot_record_id)

            async def _run() -> None:
                try:
                    await dp.start_polling(
                        bot,
                        allowed_updates=[
                            "message",
                            "edited_message",
                            "callback_query",
                            "chat_join_request",
                            "my_chat_member",
                        ],
                    )
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    log.exception("Polling приветки %s упал: %s", bot_record_id, e)

            task = asyncio.create_task(_run())
            self._bots[bot_record_id] = (bot, dp, task)
            log.info("Приветка %s запущена", bot_record_id)
            return bot

    async def stop_bot(self, bot_record_id: int) -> None:
        async with self._lock:
            entry = self._bots.pop(bot_record_id, None)
            if not entry:
                return
            bot, dp, task = entry
            try:
                await dp.stop_polling()
            except Exception:
                pass
            task.cancel()
            try:
                await asyncio.wait_for(task, timeout=5)
            except Exception:
                pass
            try:
                await bot.session.close()
            except Exception:
                pass
            log.info("Приветка %s остановлена", bot_record_id)

    async def stop_all(self) -> None:
        for bot_id in list(self._bots.keys()):
            await self.stop_bot(bot_id)

    def get_bot(self, bot_record_id: int) -> Optional[Bot]:
        entry = self._bots.get(bot_record_id)
        return entry[0] if entry else None


_manager: Optional[BotManager] = None


def get_manager() -> BotManager:
    global _manager
    if _manager is None:
        _manager = BotManager()
    return _manager


async def validate_token(token: str) -> Optional[dict]:
    """Проверяет токен. Возвращает {tg_id, username, name} или None."""
    try:
        bot = Bot(token=token)
        me = await bot.get_me()
        await bot.session.close()
        return {
            "tg_id": me.id,
            "username": me.username or "",
            "name": me.first_name or "",
        }
    except TelegramUnauthorizedError:
        return None
    except Exception as e:
        log.error("validate_token: %s", e)
        return None
