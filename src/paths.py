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


def references_dir() -> Path:
    """Папка со скриншотами кнопок CapCut для UI-автоматизации."""
    return app_dir() / "Интерфейс (скриншоты кнопок)"


def reference_defaults_dir() -> Path:
    """Встроенные (готовые) эталоны кнопок, поставляемые с софтом."""
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
        return base / "reference_defaults"
    return Path(__file__).resolve().parent / "ui_automation" / "reference_defaults"


def ui_shots_dir() -> Path:
    """Куда сохраняются скриншоты экрана при сбоях UI-автоматизации."""
    return logs_dir() / "screenshots"


def config_path() -> Path:
    return app_dir() / "config.json"
