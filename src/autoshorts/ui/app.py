"""Десктопный интерфейс.

Реализация: локальный FastAPI-бэкенд + HTML-страница, обёрнутые в нативное окно
через pywebview. Так интерфейс кроссплатформенный и легко упаковывается в .exe.
Пока это заглушка запуска — UI собирается в следующем шаге; движок полностью
доступен через CLI (`python -m autoshorts.cli voice|montage`).
"""
from __future__ import annotations

from ..logging_setup import get_logger

log = get_logger("ui")


def run_gui(config_path: str = "config.yaml") -> int:
    print(
        "Десктопный интерфейс ещё собирается. Пока используй CLI:\n"
        "  python -m autoshorts.cli voice   --cycles N\n"
        "  python -m autoshorts.cli montage --cycles N\n"
    )
    return 0
