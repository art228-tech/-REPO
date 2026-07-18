"""Мост между потоко-независимым логгером и GUI.

Логгер вызывает колбэк из любого потока (в т.ч. рабочего потока пайплайна).
Qt-сигнал с очередью безопасно доставляет строку в GUI-поток.
"""

from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtSignal

from ..logging_setup import get_callback_handler


class LogBridge(QObject):
    message = pyqtSignal(str)

    def __init__(self) -> None:
        super().__init__()
        handler = get_callback_handler()
        if handler is not None:
            handler.add_callback(self._on_message)

    def _on_message(self, text: str) -> None:
        # emit безопасен для вызова из другого потока (доставка через очередь).
        self.message.emit(text)
