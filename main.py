"""Точка входа: CapCut Автомонтаж (Windows)."""

from __future__ import annotations

import sys

from src.assets import AssetManager
from src.config import AppConfig
from src.logging_setup import get_logger, setup_logging
from src import paths


def main() -> int:
    setup_logging()
    logger = get_logger()
    logger.info("Старт приложения. Рабочая папка: %s", paths.app_dir())

    # Создаём папки-ассеты сразу, чтобы пользователь мог наполнять их из проводника.
    try:
        AssetManager(paths.assets_dir()).ensure_folders()
        paths.references_dir().mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logger.error("Не удалось создать рабочие папки: %s", e)

    config = AppConfig.load()

    # Импорт Qt здесь, чтобы консольные/тестовые сценарии не требовали PyQt6.
    from PyQt6.QtWidgets import QApplication
    from src.gui.main_window import MainWindow

    app = QApplication(sys.argv)
    window = MainWindow(config)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
