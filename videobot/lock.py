"""Замок на вторую копию программы.

Две запущенные копии дерутся за один токен: Telegram отдаёт обновления только
одному опросу и отвечает второму «terminated by other getUpdates request».
Выглядит это как бот, который то отвечает, то нет, и причина по такому симптому
не угадывается.

Замок — файл с номером процесса. Проверяется, жив ли этот процесс: после
выключения питания или снятия задачи файл остаётся, и без проверки программа
больше никогда бы не запустилась.
"""
from __future__ import annotations

import os
from pathlib import Path

from .logs import get_logger

log = get_logger("замок")

FILE_NAME = "запущено.pid"

try:
    import psutil
except ImportError:  # без psutil проверяем только своими силами
    psutil = None


def path_for(folder: Path) -> Path:
    return folder / FILE_NAME


def running_pid(folder: Path) -> int:
    """Номер живой чужой копии или ноль, если её нет."""
    target = path_for(folder)
    try:
        raw = target.read_text(encoding="utf-8").strip()
    except OSError:
        return 0

    if not raw.isdigit():
        return 0

    pid = int(raw)
    if pid == os.getpid():
        return 0
    return pid if _alive(pid) else 0


def _alive(pid: int) -> bool:
    if psutil is not None:
        try:
            return psutil.pid_exists(pid)
        except Exception:  # noqa: BLE001 - не смогли проверить, считаем мёртвым
            return False
    try:
        os.kill(pid, 0)
    except (OSError, ValueError):
        return False
    return True


def take(folder: Path) -> int:
    """Занимает замок. Ноль — заняли, иначе номер чужой живой копии."""
    folder.mkdir(parents=True, exist_ok=True)
    other = running_pid(folder)
    if other:
        log.warning("Программа уже запущена, процесс %d — вторую копию не поднимаю", other)
        return other

    try:
        path_for(folder).write_text(str(os.getpid()), encoding="utf-8")
    except OSError as exc:
        # Замок — удобство, а не условие работы: не смогли записать, идём дальше.
        log.warning("Замок поставить не вышло: %s", exc)
    return 0


def release(folder: Path) -> None:
    target = path_for(folder)
    try:
        if target.is_file() and target.read_text(encoding="utf-8").strip() == str(os.getpid()):
            target.unlink()
    except OSError:
        pass
