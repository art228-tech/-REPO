"""Менеджер помощников: каждый ловит chat_join_request своих каналов
и ставит заявку в очередь приёма."""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramUnauthorizedError
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ChatJoinRequest

from database import get_db, now

log = logging.getLogger("manager")


class HelperManager:
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
        db = get_db()
        helpers = await db.list_active_helpers()
        for h in helpers:
            await self.start_one(h["id"], h["token"])

    async def start_one(self, helper_id: int, token: str) -> Optional[Bot]:
        if helper_id in self._helpers:
            return self._helpers[helper_id][0]
        try:
            bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
            me = await bot.get_me()
        except TelegramUnauthorizedError as e:
            await self._handle_dead(helper_id, f"Unauthorized: {e}")
            return None
        except Exception as e:
            log.warning("start_one(%s): %s", helper_id, e)
            await self._handle_dead(helper_id, str(e))
            return None

        dp = Dispatcher(storage=MemoryStorage())
        self._register_join_handler(dp, helper_id)

        task = asyncio.create_task(self._poll_loop(helper_id, bot, dp))
        self._helpers[helper_id] = (bot, dp, task)
        log.info("Помощник %s (@%s) запущен", helper_id, me.username)
        return bot

    def _register_join_handler(self, dp: Dispatcher, helper_id: int) -> None:
        """Регистрирует у помощника обработчик chat_join_request."""

        @dp.chat_join_request()
        async def on_join_request(req: ChatJoinRequest) -> None:
            db = get_db()
            ch = await db.get_channel_by_chat(helper_id, req.chat.id)
            if ch is None:
                # канал не привязан в нашем боте — игнорим
                return
            if not ch["auto_accept"]:
                log.info(
                    "[helper %s] заявка %s в канал %s — автоприём выключен",
                    helper_id, req.from_user.id, req.chat.id,
                )
                return
            delay = int(ch["accept_delay"] or 0)
            if delay <= 0:
                # мгновенный приём
                try:
                    await req.approve()
                    log.info(
                        "[helper %s] заявка %s принята в %s",
                        helper_id, req.from_user.id, req.chat.id,
                    )
                except TelegramUnauthorizedError as e:
                    await get_manager().report_helper_error(helper_id, e)
                except Exception as e:
                    log.warning("approve failed: %s", e)
                return
            # ставим в очередь
            await db.schedule_accept(
                helper_id, ch["id"], req.chat.id, req.from_user.id,
                now() + delay,
            )
            log.info(
                "[helper %s] заявка %s в очереди приёма на канал %s (через %s с)",
                helper_id, req.from_user.id, req.chat.id, delay,
            )

    async def _poll_loop(self, helper_id: int, bot: Bot, dp: Dispatcher) -> None:
        try:
            await dp.start_polling(
                bot, allowed_updates=["chat_join_request"]
            )
        except TelegramUnauthorizedError as e:
            await self._handle_dead(helper_id, f"Unauthorized: {e}")
        except asyncio.CancelledError:
            return
        except Exception as e:
            log.exception("poll_loop(%s): %s", helper_id, e)

    async def stop_one(self, helper_id: int) -> None:
        entry = self._helpers.pop(helper_id, None)
        if not entry:
            return
        bot, dp, task = entry
        try:
            await dp.stop_polling()
        except Exception:
            pass
        task.cancel()
        try:
            await bot.session.close()
        except Exception:
            pass

    async def stop_all(self) -> None:
        for hid in list(self._helpers.keys()):
            await self.stop_one(hid)

    async def report_helper_error(self, helper_id: int, exc: Exception) -> bool:
        msg = str(exc)
        if isinstance(exc, TelegramUnauthorizedError) or "unauthorized" in msg.lower():
            await self._handle_dead(helper_id, msg)
            return True
        return False

    async def _handle_dead(self, helper_id: int, error: str) -> None:
        db = get_db()
        helper = await db.get_helper(helper_id)
        await db.mark_helper_dead(helper_id, error[:500])

        entry = self._helpers.pop(helper_id, None)
        if entry:
            _, _, task = entry
            task.cancel()
            try:
                await entry[0].session.close()
            except Exception:
                pass

        name = (helper["name"] or helper["username"] or f"id{helper_id}") if helper else f"id{helper_id}"
        text = (
            f"\u26a0\ufe0f <b>Помощник заморожен/удалён</b>\n\n"
            f"<b>{name}</b>\n"
            f"<code>{error[:200]}</code>\n\n"
            f"Автоприём по его каналам не работает."
        )
        if self._main_bot:
            for admin_id in self._admin_ids:
                try:
                    await self._main_bot.send_message(admin_id, text)
                except Exception as e:
                    log.warning("уведомление админу %s: %s", admin_id, e)


_manager: HelperManager | None = None


def get_manager() -> HelperManager:
    global _manager
    if _manager is None:
        _manager = HelperManager()
    return _manager
