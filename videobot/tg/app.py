"""Запуск бота: сборка, фоновые задачи, работа в отдельном потоке.

Бот подключается длинным опросом — сам стучится в Telegram и спрашивает, есть
ли что новое. Входящих соединений нет, поэтому ни белый IP, ни домен, ни
проброс портов на роутере не нужны: работает из-за домашнего роутера так же,
как в датацентре.

Живёт бот в своём потоке со своим циклом событий, потому что главный поток
занят окном программы.
"""
from __future__ import annotations

import asyncio
import threading

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from .. import uploader
from ..db import Base
from ..guard import Guard
from ..logs import get_logger
from . import admin, reminders, worker
from .access import Access

log = get_logger("бот")


def build(base: Base, settings, guard: Guard) -> tuple[Bot, Dispatcher]:
    bot = Bot(settings.token,
              default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dispatcher = Dispatcher(storage=MemoryStorage())

    access = Access(base, settings, guard)
    dispatcher.message.middleware(access)
    dispatcher.callback_query.middleware(access)

    # Админка идёт первой: у её кнопок свой префикс, и она не перехватывает
    # чужие сообщения — зато /start админа должен попасть именно в неё.
    dispatcher.include_router(admin.router)
    dispatcher.include_router(worker.router)
    return bot, dispatcher


async def serve(base: Base, settings, guard: Guard, stopping: asyncio.Event) -> None:
    bot, dispatcher = build(base, settings, guard)

    me = await bot.get_me()
    log.info("Бот @%s на связи", me.username)

    tasks = [
        asyncio.create_task(guard.watch()),
        asyncio.create_task(uploader.loop(bot, base, guard)),
        asyncio.create_task(reminders.loop(bot, base, settings.reminder_after_hours)),
        asyncio.create_task(dispatcher.start_polling(bot, handle_signals=False)),
        asyncio.create_task(stopping.wait()),
    ]
    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

    for task in pending:
        task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)
    for task in done:
        if task.exception() is not None and not isinstance(task.exception(), asyncio.CancelledError):
            raise task.exception()

    await bot.session.close()
    log.info("Бот остановлен")


class Runner:
    """Бот в фоновом потоке: окно программы включает и выключает его кнопкой."""

    def __init__(self, base: Base, settings, guard: Guard):
        self.base = base
        self.settings = settings
        self.guard = guard
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stopping: asyncio.Event | None = None
        self.error: str = ""

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self.error = ""
        self._thread = threading.Thread(target=self._run, daemon=True, name="бот")
        self._thread.start()

    def stop(self, timeout: float = 10.0) -> None:
        if not self.running or self._loop is None or self._stopping is None:
            return
        self._loop.call_soon_threadsafe(self._stopping.set)
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        self._stopping = asyncio.Event()
        try:
            loop.run_until_complete(
                serve(self.base, self.settings, self.guard, self._stopping))
        except Exception as exc:  # noqa: BLE001 - в окно должна попасть причина
            self.error = str(exc)
            log.error("Бот остановился: %s", exc)
        finally:
            try:
                loop.run_until_complete(loop.shutdown_asyncgens())
            finally:
                loop.close()
                self._loop = None
