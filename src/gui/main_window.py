"""Главное окно с тремя вкладками."""

from __future__ import annotations

from PyQt6.QtWidgets import QMainWindow, QTabWidget

from ..config import AppConfig
from .logs_tab import LogsTab
from .run_tab import RunTab
from .settings_tab import SettingsTab


class MainWindow(QMainWindow):
    def __init__(self, config: AppConfig) -> None:
        super().__init__()
        self.config = config
        self.setWindowTitle("CapCut Автомонтаж")
        self.resize(900, 640)

        tabs = QTabWidget()
        tabs.addTab(SettingsTab(config), "Настройки")
        tabs.addTab(RunTab(config), "Запуск")
        tabs.addTab(LogsTab(), "Отстук")
        self.setCentralWidget(tabs)
