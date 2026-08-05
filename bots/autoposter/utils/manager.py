"""Менеджер ботов-помощников: запуск polling, отслеживание заморозки.

Каждый помощник — отдельный Bot + Dispatcher + фоновая задача с polling.
Если при работе с помощником прилетит TelegramUnauthorizedError
(токен невалиден, бота забанили/удалили) — помощник помечается dead,
админ получает уведомление, polling останавливается.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramUnauthorizedError, TelegramForbiddenError
from aiogram.fsm.storage.memory import MemoryStorage

from database import get_db

log = logging.getLogger("manager")


class HelperManager:
    """Держит запущенными polling-и всех помощников.

    Помощники нужны только чтобы делать API-запросы (постить, удалять,
    проверять права) от своего имени. Своих хендлеров у них нет —
    Dispatcher просто крутится, чтобы поддерживать сессию.
    """

    def __init__(self) -> None:
        self._helpers: dict[int, tuple[Bot, Dispatcher, asyncio.Task]] = {}
        self._main_bot: Bot | None = None
        self._admin_ids: list[int] = []

    def set_main_bot(self, main_bot: Bot, admin_ids: list[int]) -> None:
        self._main_bot = main_bot
        self._admin_ids = admin_ids

    def get_helper_bot(self, helper_id: int) -> Optional[Bot]:
        entry = self._helpers.get(helper_id)
        return entry[0] if entry else None

    async def start_all(self) -> None:
        """Поднимает polling всех живых помощников из БД."""
        db = get_db()
        helpers = await db.list_active_helpers()
        for h in helpers:
            await self.start_one(h["id"], h["token"])

    async def start_one(self, helper_id: int, token: str) -> Optional[Bot]:
        """Запускает polling одного помощника."""
        if helper_id in self._helpers:
            return self._helpers[helper_id][0]
        try:
            bot = Bot(
                token=token,
                default=DefaultBotProperties(parse_mode=ParseMode.HTML),
            )
            # верификация токена
            me = await bot.get_me()
        except TelegramUnauthorizedError as e:
            await self._handle_dead(helper_id, f"Unauthorized: {e}")
            return None
        except Exception as e:
            log.warning("start_one(%s): %s", helper_id, e)
            await self._handle_dead(helper_id, str(e))
            return None

        dp = Dispatcher(storage=MemoryStorage())
        task = asyncio.create_task(self._poll_loop(helper_id, bot, dp))
        self._helpers[helper_id] = (bot, dp, task)
        log.info("Помощник %s (@%s) запущен", helper_id, me.username)
        return bot

    async def stop_one(self, helper_id: int) -> None:
        entry = self._helpers.pop(helper_id, None)
        if not entry:
            return
        bot, dp, task = entry
        await dp.stop_polling()
        task.cancel()
        try:
            await bot.session.close()
        except Exception:
            pass

    async def stop_all(self) -> None:
        for hid in list(self._helpers.keys()):
            await self.stop_one(hid)

    async def _poll_loop(self, helper_id: int, bot: Bot, dp: Dispatcher) -> None:
        """Polling помощника. Если падает с Unauthorized — помечаем dead."""
        try:
            await dp.start_polling(bot, allowed_updates=[])
        except TelegramUnauthorizedError as e:
            await self._handle_dead(helper_id, f"Unauthorized: {e}")
        except asyncio.CancelledError:
            return
        except Exception as e:
            log.exception("poll_loop(%s) error: %s", helper_id, e)

    async def _handle_dead(self, helper_id: int, error: str) -> None:
        """Помечает помощника как dead и уведомляет админа."""
        db = get_db()
        helper = await db.get_helper(helper_id)
        await db.mark_helper_dead(helper_id, error[:500])

        # выключаем постинг на всех каналах этого помощника
        channels = await db.list_channels(helper_id)
        for ch in channels:
            st = await db.get_posting_state(ch["id"])
            if st and st["is_running"]:
                await db.set_posting_state(ch["id"], is_running=0)

        # снимаем polling
        entry = self._helpers.pop(helper_id, None)
        if entry:
            _, _, task = entry
            task.cancel()
            try:
                await entry[0].session.close()
            except Exception:
                pass

        # уведомляем админов
        name = helper["name"] or helper["username"] or f"id{helper_id}" if helper else f"id{helper_id}"
        text = (
            f"\u26a0\ufe0f <b>Помощник заморожен/удалён</b>\n\n"
            f"<b>{name}</b>\n"
            f"<code>{error[:200]}</code>\n\n"
            f"Постинг по каналам этого помощника остановлен."
        )
        if self._main_bot:
            for admin_id in self._admin_ids:
                try:
                    await self._main_bot.send_message(admin_id, text)
                except Exception as e:
                    log.warning("уведомление админу %s: %s", admin_id, e)

    async def report_helper_error(self, helper_id: int, exc: Exception) -> bool:
        """Внешний код может сообщить, что помощник упал с Unauthorized.
        Возвращает True, если ошибка распознана как «бот мёртв»."""
        msg = str(exc)
        if isinstance(exc, TelegramUnauthorizedError) or "unauthorized" in msg.lower():
            await self._handle_dead(helper_id, msg)
            return True
        # Forbidden может быть «бот заблокирован» — но в постинге в канал
        # это обычно «нет прав постить», что не = мёртв. Не помечаем dead.
        return False


_manager: HelperManager | None = None


def get_manager() -> HelperManager:
    global _manager
    if _manager is None:
        _manager = HelperManager()
    return _manager
