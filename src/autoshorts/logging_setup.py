"""Логирование: одновременно в консоль и в файл.

Файловые логи нужны, чтобы при баге можно было прислать лог и быстро найти
причину, ничего при этом не теряя из уже загруженных материалов.
"""
from __future__ import annotations

import logging
import logging.handlers
import sys
from datetime import datetime
from pathlib import Path

_CONFIGURED = False


def setup_logging(logs_dir: str | Path = "logs", level: str = "INFO",
                  keep_files: int = 20) -> logging.Logger:
    """Настроить корневой логгер один раз за процесс.

    Пишет полный лог в logs/run-YYYYmmdd-HHMMSS.log и коротко в консоль.
    """
    global _CONFIGURED
    logger = logging.getLogger("autoshorts")
    if _CONFIGURED:
        return logger

    logs_path = Path(logs_dir)
    logs_path.mkdir(parents=True, exist_ok=True)

    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Файл: всегда DEBUG (максимум подробностей для разбора багов).
    logfile = logs_path / f"run-{datetime.now():%Y%m%d-%H%M%S}.log"
    file_handler = logging.FileHandler(logfile, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    # Консоль: уровень из конфига.
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(getattr(logging, level.upper(), logging.INFO))
    console.setFormatter(fmt)
    logger.addHandler(console)

    _prune_old_logs(logs_path, keep_files)

    logger.debug("Логирование инициализировано, файл: %s", logfile)
    _CONFIGURED = True
    return logger


def _prune_old_logs(logs_path: Path, keep_files: int) -> None:
    files = sorted(logs_path.glob("run-*.log"), key=lambda p: p.stat().st_mtime,
                   reverse=True)
    for old in files[keep_files:]:
        try:
            old.unlink()
        except OSError:
            pass


def get_logger(name: str | None = None) -> logging.Logger:
    base = logging.getLogger("autoshorts")
    return base.getChild(name) if name else base
