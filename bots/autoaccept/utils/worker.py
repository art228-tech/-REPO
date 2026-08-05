"""Воркер: раз в N сек берёт из БД заявки, которым пришло время, и принимает их
через нужного помощника. Переживает перезапуск (всё в БД)."""
from __future__ import annotations

import asyncio
import logging
import time

from aiogram.exceptions import TelegramUnauthorizedError

from database import get_db
from utils.manager import get_manager

log = logging.getLogger("worker")


class AcceptWorker:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())
            log.info("AcceptWorker запущен")

    async def _loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(5)
                await self._tick()
            except asyncio.CancelledError:
                return
            except Exception as e:
                log.exception("worker loop: %s", e)

    async def _tick(self) -> None:
        db = get_db()
        manager = get_manager()
        ts = int(time.time())
        due = await db.due_accepts(ts)
        for pa in due:
            bot = manager.get_helper_bot(pa["helper_id"])
            if bot is None:
                # помощник не запущен (заморожен/удалён) — выбрасываем заявку
                await db.remove_pending_accept(pa["id"])
                continue
            try:
                await bot.approve_chat_join_request(pa["chat_id"], pa["user_id"])
                log.info(
                    "[helper %s] заявка %s принята в %s (отложено)",
                    pa["helper_id"], pa["user_id"], pa["chat_id"],
                )
            except TelegramUnauthorizedError as e:
                await manager.report_helper_error(pa["helper_id"], e)
                # запись остаётся — после восстановления возможно примем
                continue
            except Exception as e:
                # User_already_participant, Hide_request_already_accepted и т.п.
                # Не страшно — просто убираем из очереди.
                log.warning(
                    "approve failed helper=%s user=%s chat=%s: %s",
                    pa["helper_id"], pa["user_id"], pa["chat_id"], e,
                )
            await db.remove_pending_accept(pa["id"])


_worker: AcceptWorker | None = None


def get_worker() -> AcceptWorker:
    global _worker
    if _worker is None:
        _worker = AcceptWorker()
    return _worker
