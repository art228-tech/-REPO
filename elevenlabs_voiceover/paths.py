"""Расположение пользовательских данных приложения."""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_DIR_NAME = "ElevenLabsVoiceover"


def user_data_dir() -> Path:
    """Постоянная папка приложения.

    На Windows это %APPDATA%\\ElevenLabsVoiceover. Данные намеренно лежат вне
    папки программы: при замене exe или переустановке настройки, база прогресса
    и логи должны сохраняться.
    """
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
        root = Path(base) if base else Path.home() / "AppData" / "Roaming"
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support"
    else:
        base = os.environ.get("XDG_DATA_HOME")
        root = Path(base) if base else Path.home() / ".local" / "share"

    path = root / APP_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_path() -> Path:
    return user_data_dir() / "config.json"


def state_db_path() -> Path:
    return user_data_dir() / "state.sqlite3"


def logs_dir() -> Path:
    path = user_data_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def reports_dir() -> Path:
    path = user_data_dir() / "reports"
    path.mkdir(parents=True, exist_ok=True)
    return path


def app_root() -> Path:
    """Папка, из которой запущена программа (учитывает сборку PyInstaller)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent
