"""Журнал: в файл, в окно и отдельной полкой — ошибки.

Ошибки складываются вторым списком нарочно. В общем потоке они тонут среди
обычных строк, а нужны они как раз тогда, когда что-то не работает и надо
быстро сказать, что именно.

Сбой при запуске пишется отдельным файлом `сбой.txt`: программа в этот момент
может не дожить до окна, и показать причину больше негде.
"""
from __future__ import annotations

import logging
import platform
import sys
import traceback
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Callable

ROOT = "videobot"
CRASH_NAME = "сбой.txt"

_listeners: list[Callable[[str], None]] = []
_recent: deque[str] = deque(maxlen=500)
_errors: deque[str] = deque(maxlen=100)
_folder: Path | None = None


class _Collect(logging.Handler):
    """Держит хвост журнала для окна и отдельно — ошибки."""

    def emit(self, record: logging.LogRecord) -> None:
        line = self.format(record)
        _recent.append(line)
        if record.levelno >= logging.WARNING:
            _errors.append(line)
        for listener in list(_listeners):
            try:
                listener(line)
            except Exception:  # noqa: BLE001 - окно не должно ронять журнал
                pass


def setup(folder: Path, verbose: bool = False) -> Path:
    """Включает запись. Возвращает путь к файлу журнала."""
    global _folder
    folder.mkdir(parents=True, exist_ok=True)
    _folder = folder
    target = folder / f"{datetime.now():%Y-%m-%d}.log"

    root = logging.getLogger(ROOT)
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    root.handlers.clear()

    plain = logging.Formatter("%(asctime)s  %(levelname)-7s  %(name)-12s  %(message)s",
                              "%H:%M:%S")

    to_file = logging.FileHandler(target, encoding="utf-8")
    to_file.setFormatter(plain)
    root.addHandler(to_file)

    collect = _Collect()
    collect.setFormatter(plain)
    root.addHandler(collect)

    # aiogram шумит на каждом опросе Telegram, и в окне от этого не видно
    # собственных сообщений бота. Но ошибки от него нужны, поэтому не глушим
    # совсем, а поднимаем порог.
    logging.getLogger("aiogram").setLevel(logging.WARNING)
    logging.getLogger("aiogram").addHandler(to_file)
    logging.getLogger("aiogram").addHandler(collect)
    return target


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"{ROOT}.{name}")


def listen(listener: Callable[[str], None]) -> None:
    _listeners.append(listener)


def recent() -> list[str]:
    return list(_recent)


def errors() -> list[str]:
    """Только предупреждения и ошибки — то, что нужно, когда что-то не так."""
    return list(_errors)


def folder() -> Path | None:
    return _folder


def environment() -> str:
    """Окружение — первое, что спрашивают, когда программа не запускается."""
    return "\n".join([
        "Программа:   videobot",
        f"Python:      {sys.version.splitlines()[0]}",
        f"Запущен как: {sys.executable}",
        f"Система:     {platform.platform()}",
        f"Папка:       {Path(__file__).resolve().parent.parent}",
        f"Время:       {datetime.now():%Y-%m-%d %H:%M:%S}",
    ])


def crash(where: Path, error: BaseException) -> Path:
    """Пишет сбой отдельным файлом и возвращает путь к нему.

    Вызывается в том числе тогда, когда журнал ещё не настроен, поэтому не
    полагается ни на логгер, ни на то, что папка существует.
    """
    target = where / CRASH_NAME
    text = "\n".join([
        "Программа не смогла запуститься.",
        "",
        environment(),
        "",
        "Что случилось:",
        "".join(traceback.format_exception(type(error), error, error.__traceback__)),
    ])
    try:
        where.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    except OSError:
        pass
    return target
