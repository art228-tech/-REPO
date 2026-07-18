"""Вкладка «Запуск»: число циклов, старт, прогресс. Пайплайн — в отдельном потоке."""

from __future__ import annotations

from PyQt6.QtCore import QObject, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..assets import AssetManager
from ..config import AppConfig
from ..logging_setup import get_logger
from ..pipeline import Pipeline
from .. import paths

logger = get_logger()


class PipelineWorker(QObject):
    finished = pyqtSignal()
    progress = pyqtSignal(int, int)

    def __init__(self, config: AppConfig, cycles: int) -> None:
        super().__init__()
        self.config = config
        self.cycles = cycles
        self.pipeline = Pipeline(
            config,
            AssetManager(paths.assets_dir()),
            progress_cb=lambda i, n: self.progress.emit(i, n),
        )

    def run(self) -> None:
        try:
            self.pipeline.run(self.cycles)
        except Exception as e:  # noqa: BLE001 — любые сбои в лог, не роняем GUI
            logger.exception("Непредвиденная ошибка в пайплайне: %s", e)
        finally:
            self.finished.emit()

    def stop(self) -> None:
        self.pipeline.request_stop()


class RunTab(QWidget):
    def __init__(self, config: AppConfig) -> None:
        super().__init__()
        self.config = config
        self._thread: QThread | None = None
        self._worker: PipelineWorker | None = None

        self.cycles = QSpinBox()
        self.cycles.setRange(1, 1000)
        self.cycles.setValue(max(1, config.cycles))

        self.btn_start = QPushButton("Запустить")
        self.btn_stop = QPushButton("Остановить")
        self.btn_stop.setEnabled(False)
        self.btn_start.clicked.connect(self._start)
        self.btn_stop.clicked.connect(self._stop)

        controls = QGroupBox("Запуск автомонтажа")
        controls_layout = QHBoxLayout(controls)
        controls_layout.addWidget(QLabel("Количество роликов:"))
        controls_layout.addWidget(self.cycles)
        controls_layout.addStretch(1)
        controls_layout.addWidget(self.btn_start)
        controls_layout.addWidget(self.btn_stop)

        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.status = QLabel("Готово к запуску.")

        layout = QVBoxLayout(self)
        layout.addWidget(controls)
        layout.addWidget(self.progress)
        layout.addWidget(self.status)
        layout.addStretch(1)

    def _start(self) -> None:
        cycles = self.cycles.value()
        self.config.cycles = cycles
        try:
            self.config.save()
        except OSError:
            pass

        self.progress.setRange(0, cycles)
        self.progress.setValue(0)
        self.status.setText("Работаю…")
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)

        self._thread = QThread()
        self._worker = PipelineWorker(self.config, cycles)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._thread.start()

    def _stop(self) -> None:
        if self._worker is not None:
            self._worker.stop()
            self.status.setText("Останавливаю после текущего цикла…")

    def _on_progress(self, i: int, n: int) -> None:
        self.progress.setValue(i)
        self.status.setText(f"Готово роликов: {i} из {n}")

    def _on_finished(self) -> None:
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait()
        self._thread = None
        self._worker = None
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.status.setText("Завершено. Подробности — во вкладке «Отстук».")
