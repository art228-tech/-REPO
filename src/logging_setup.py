"""Единая система логирования.

Логи одновременно:
  * пишутся в файл logs/app_YYYY-MM-DD.log (для отправки разработчику);
  * складываются в память (кольцевой буфер) для вкладки «Отстук»;
  * рассылаются подписчикам (GUI) через колбэки в реальном времени.

Модуль намеренно НЕ зависит от Qt, чтобы его можно было использовать в тестах
и в консоли. GUI подключает свой обработчик отдельно.
"""

from __future__ import annotations

import logging
from collections import deque
from datetime import datetime
from logging import Handler, LogRecord
from typing import Callable, Deque

from . import paths

LOGGER_NAME = "capcut_auto"
_MAX_BUFFER = 5000

_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"
_DATE_FORMAT = "%H:%M:%S"


class CallbackHandler(Handler):
    """Пробрасывает отформатированные строки лога в список колбэков."""

    def __init__(self) -> None:
        super().__init__()
        self._buffer: Deque[str] = deque(maxlen=_MAX_BUFFER)
        self._callbacks: list[Callable[[str], None]] = []

    def emit(self, record: LogRecord) -> None:
        try:
            msg = self.format(record)
        except Exception:  # noqa: BLE001 — логирование не должно ронять приложение
            return
        self._buffer.append(msg)
        for cb in list(self._callbacks):
            try:
                cb(msg)
            except Exception:  # noqa: BLE001
                pass

    def add_callback(self, cb: Callable[[str], None]) -> None:
        self._callbacks.append(cb)
        # Отдаём уже накопленное, чтобы вкладка не была пустой при подключении.
        for line in list(self._buffer):
            cb(line)

    def remove_callback(self, cb: Callable[[str], None]) -> None:
        if cb in self._callbacks:
            self._callbacks.remove(cb)

    def snapshot(self) -> list[str]:
        return list(self._buffer)


_callback_handler: CallbackHandler | None = None


def setup_logging() -> logging.Logger:
    """Инициализирует и возвращает корневой логгер приложения (идемпотентно)."""
    global _callback_handler

    logger = logging.getLogger(LOGGER_NAME)
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

    logs = paths.logs_dir()
    logs.mkdir(parents=True, exist_ok=True)
    file_path = logs / f"app_{datetime.now():%Y-%m-%d}.log"
    file_handler = logging.FileHandler(file_path, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    ))
    logger.addHandler(file_handler)

    _callback_handler = CallbackHandler()
    _callback_handler.setLevel(logging.INFO)
    _callback_handler.setFormatter(formatter)
    logger.addHandler(_callback_handler)

    return logger


def get_logger() -> logging.Logger:
    return logging.getLogger(LOGGER_NAME)


def get_callback_handler() -> CallbackHandler | None:
    return _callback_handler
