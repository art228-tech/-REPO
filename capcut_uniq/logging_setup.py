"""Журналирование.

Два потока: краткий в консоль/интерфейс и подробный в файл. Файл рассчитан на
то, чтобы его можно было целиком переслать для разбора — в шапке пишется
окружение, дальше идёт каждое действие с числами.
"""
from __future__ import annotations

import logging
import platform
import sys
from datetime import datetime
from pathlib import Path

_ROOT = "capcut_uniq"
_FILE_FORMAT = "%(asctime)s  %(levelname)-7s  %(name)-24s  %(message)s"
_CONSOLE_FORMAT = "%(message)s"


def get_logger(name: str = "") -> logging.Logger:
    return logging.getLogger(f"{_ROOT}.{name}" if name else _ROOT)


def setup(log_dir: Path, verbose: bool = False) -> Path:
    """Поднимает журналирование и возвращает путь к файлу журнала."""
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = log_dir / f"run_{stamp}.log"

    root = get_logger()
    root.setLevel(logging.DEBUG)
    root.handlers.clear()
    root.propagate = False

    file_handler = logging.FileHandler(path, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(_FILE_FORMAT))
    root.addHandler(file_handler)

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.DEBUG if verbose else logging.INFO)
    console.setFormatter(logging.Formatter(_CONSOLE_FORMAT))
    root.addHandler(console)

    _write_header(root, path)
    return path


def add_handler(handler: logging.Handler) -> None:
    """Подключает дополнительный приёмник — используется графическим интерфейсом."""
    get_logger().addHandler(handler)


def _write_header(logger: logging.Logger, path: Path) -> None:
    logger.debug("=" * 78)
    logger.debug("Журнал: %s", path)
    logger.debug("Время запуска: %s", datetime.now().isoformat(timespec="seconds"))
    logger.debug("Система: %s %s", platform.system(), platform.release())
    logger.debug("Python: %s", sys.version.replace("\n", " "))
    logger.debug("=" * 78)
