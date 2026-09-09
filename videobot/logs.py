"""Журнал: одновременно в файл и в окно программы.

Окно показывает последние строки, чтобы было видно, чем бот занят, а файл
остаётся на потом — по нему разбирают, что случилось ночью.
"""
from __future__ import annotations

import logging
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Callable

ROOT = "videobot"

_listeners: list[Callable[[str], None]] = []
_recent: deque[str] = deque(maxlen=500)


class _ToWindow(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        line = self.format(record)
        _recent.append(line)
        for listener in list(_listeners):
            try:
                listener(line)
            except Exception:  # noqa: BLE001 - окно не должно ронять журнал
                pass


def setup(folder: Path, verbose: bool = False) -> Path:
    """Включает запись. Возвращает путь к файлу журнала."""
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{datetime.now():%Y-%m-%d}.log"

    root = logging.getLogger(ROOT)
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    root.handlers.clear()

    plain = logging.Formatter("%(asctime)s  %(name)-12s  %(message)s", "%H:%M:%S")

    to_file = logging.FileHandler(target, encoding="utf-8")
    to_file.setFormatter(plain)
    root.addHandler(to_file)

    to_window = _ToWindow()
    to_window.setFormatter(plain)
    root.addHandler(to_window)

    # aiogram шумит на каждом опросе Telegram, и в окне от этого не видно
    # собственных сообщений бота.
    logging.getLogger("aiogram").setLevel(logging.WARNING)
    return target


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"{ROOT}.{name}")


def listen(listener: Callable[[str], None]) -> None:
    _listeners.append(listener)


def recent() -> list[str]:
    return list(_recent)
