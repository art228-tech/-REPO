"""Вкладка «Отстук» — логи в удобном виде + экспорт файла для разработчика."""

from __future__ import annotations

from datetime import datetime

from PyQt6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .log_bridge import LogBridge


class LogsTab(QWidget):
    def __init__(self) -> None:
        super().__init__()

        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setMaximumBlockCount(10000)
        self.view.setStyleSheet(
            "QPlainTextEdit { font-family: Consolas, 'Courier New', monospace; "
            "font-size: 12px; background: #1e1e1e; color: #e6e6e6; }"
        )

        self.btn_export = QPushButton("Экспортировать логи в файл…")
        self.btn_clear = QPushButton("Очистить")
        self.btn_export.clicked.connect(self._export)
        self.btn_clear.clicked.connect(self.view.clear)

        buttons = QHBoxLayout()
        buttons.addWidget(self.btn_export)
        buttons.addWidget(self.btn_clear)
        buttons.addStretch(1)

        layout = QVBoxLayout(self)
        layout.addLayout(buttons)
        layout.addWidget(self.view)

        self.bridge = LogBridge()
        self.bridge.message.connect(self._append)

    def _append(self, text: str) -> None:
        self.view.appendPlainText(text)

    def _export(self) -> None:
        default = f"capcut-logs_{datetime.now():%Y-%m-%d_%H-%M-%S}.txt"
        path, _ = QFileDialog.getSaveFileName(
            self, "Сохранить логи", default, "Текстовые файлы (*.txt)"
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.view.toPlainText())
            QMessageBox.information(self, "Готово", f"Логи сохранены:\n{path}")
        except OSError as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось сохранить:\n{e}")
