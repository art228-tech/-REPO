"""Определение путей приложения.

Все рабочие данные (папки-ассеты, config.json, логи) лежат РЯДОМ с софтом,
как и просил пользователь. При запуске из исходников это корень репозитория,
при запуске собранного .exe — папка рядом с exe.
"""

from __future__ import annotations

import sys
from pathlib import Path


def app_dir() -> Path:
    """Папка, рядом с которой лежат данные приложения."""
    if getattr(sys, "frozen", False):
        # Собранный PyInstaller .exe
        return Path(sys.executable).resolve().parent
    # Запуск из исходников: корень репозитория (на уровень выше src/)
    return Path(__file__).resolve().parent.parent


def assets_dir() -> Path:
    return app_dir() / "Ассеты"


def logs_dir() -> Path:
    return app_dir() / "logs"


def config_path() -> Path:
    return app_dir() / "config.json"
