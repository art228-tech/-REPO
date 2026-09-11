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
import traceback

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramUnauthorizedError
from aiogram.fsm.storage.memory import MemoryStorage

from .. import config as config_module
from .. import uploader
from ..db import Base
from ..errors import PipelineError
from ..guard import Guard
from ..logs import get_logger
from . import admin, reminders, worker
from .access import Access

log = get_logger("бот")


# Диспетчер собирается один раз за всё время работы программы и дальше
# переиспользуется. Роутеры в aiogram привязываются к диспетчеру навсегда:
# второй диспетчер на тех же роутерах падает с «Router is already attached».
# А остановить и снова запустить бота кнопкой — обычное дело, и раньше вторая
# попытка обрывалась именно на этом.
_dispatcher: Dispatcher | None = None


def dispatcher_for(base: Base, settings, guard: Guard) -> Dispatcher:
    global _dispatcher
    if _dispatcher is not None:
        return _dispatcher

    dispatcher = Dispatcher(storage=MemoryStorage())

    # Доступ держит те же объекты настроек и базы, что и окно программы,
    # поэтому смена токена или выдача доступа доходят до него без пересборки.
    access = Access(base, settings, guard)
    dispatcher.message.middleware(access)
    dispatcher.callback_query.middleware(access)

    # Админка идёт первой: у её кнопок свой префикс, и она не перехватывает
    # чужие сообщения — зато /start админа должен попасть именно в неё.
    dispatcher.include_router(admin.router)
    dispatcher.include_router(worker.router)

    _dispatcher = dispatcher
    return dispatcher


def forget_dispatcher() -> None:
    """Сбрасывает собранный диспетчер. Нужно тестам, чтобы не тянуть чужой."""
    global _dispatcher
    _dispatcher = None


async def serve(base: Base, settings, guard: Guard, stopping: asyncio.Event) -> None:
    # Бот пересоздаётся на каждый запуск: токен и прокси могли поменять в окне,
    # а они зашиты в объект бота. Диспетчер при этом остаётся прежним.
    proxy = config_module.proxy(settings.proxy_url)
    if proxy.startswith("socks"):
        # Пакет для socks ставится отдельно: на части машин с Windows его
        # установка срывается и уносит с собой всю остальную.
        try:
            import aiohttp_socks  # noqa: F401
        except ImportError as exc:
            raise PipelineError(
                "Для прокси socks нужен отдельный пакет — сразу он не ставится.\n\n"
                "Поставьте его один раз: закройте программу, откройте папку с "
                "ней и запустите  run.bat socks\n\n"
                "Либо укажите обычный прокси http — он работает без этого пакета."
            ) from exc

    session = AiohttpSession(proxy=proxy) if proxy else None
    if proxy:
        log.info("Иду к Telegram через прокси")

    bot = Bot(settings.token, session=session,
              default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dispatcher = dispatcher_for(base, settings, guard)

    # Первый же запрос к Telegram отвечает на оба главных вопроса: приняли ли
    # токен и вообще достучались ли. Обе причины по сообщению aiogram не
    # понять, а других на этом шаге практически не бывает.
    try:
        me = await bot.get_me()
    except TelegramUnauthorizedError as exc:
        raise PipelineError(
            "Telegram не принял токен. Проверьте, что скопировали его целиком "
            "и что бот не удалён. Новый токен берётся у @BotFather командой "
            "/mybots → бот → API Token."
        ) from exc
    except Exception as exc:  # noqa: BLE001 - к Telegram не достучались
        # В России api.telegram.org заблокирован, и это самая частая причина.
        # VPN в режиме «Proxy» не помогает: он уводит браузер, а программа
        # идёт мимо него.
        where = "через прокси " if proxy else ""
        raise PipelineError(
            f"Не достучался до Telegram {where}— чаще всего это блокировка.\n\n"
            "Включите VPN в режиме TUN (не Proxy) или впишите адрес прокси в "
            "настройках.\n\n"
            f"Что ответила сеть: {type(exc).__name__}: {exc}"
        ) from exc

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
            self.error = f"{type(exc).__name__}: {exc}"
            # Одной строки в окне мало: по «Unauthorized» не понять, что токен
            # чужой, а по «Connection refused» — что дело в прокси. Разбор
            # уходит в журнал целиком и потом в отчёт.
            log.error("Бот остановился — %s\n%s", self.error, traceback.format_exc())
        finally:
            try:
                loop.run_until_complete(loop.shutdown_asyncgens())
            finally:
                loop.close()
                self._loop = None
