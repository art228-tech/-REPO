"""Crash-safe состояние: чекпоинты прогресса и учёт использованных материалов.

Требование: баг → фикс → продолжение без потери данных. Поэтому прогресс
пишется атомарно в JSON после каждого шага. Повторный запуск подхватывает
состояние и продолжает с места остановки.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any


class StateStore:
    """Простое атомарное key-value хранилище на JSON-файле."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._data: dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            try:
                self._data = json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                # Повреждённый файл не должен ронять запуск — начинаем чисто,
                # но сохраняем битую копию для разбора.
                backup = self.path.with_suffix(".corrupt.json")
                try:
                    self.path.replace(backup)
                except OSError:
                    pass
                self._data = {}

    def _flush(self) -> None:
        """Атомарная запись: пишем во временный файл и заменяем оригинал."""
        tmp_fd, tmp_name = tempfile.mkstemp(dir=str(self.path.parent),
                                            suffix=".tmp")
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as fh:
                json.dump(self._data, fh, ensure_ascii=False, indent=2)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_name, self.path)
        finally:
            if os.path.exists(tmp_name):
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._data[key] = value
            self._flush()

    def update(self, **kwargs: Any) -> None:
        with self._lock:
            self._data.update(kwargs)
            self._flush()

    def as_dict(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._data)
