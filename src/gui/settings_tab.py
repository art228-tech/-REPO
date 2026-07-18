"""Вкладка «Настройки»: имя проекта, папки, проценты субтитров, экспорт."""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..config import AppConfig
from .. import paths


class SettingsTab(QWidget):
    def __init__(self, config: AppConfig) -> None:
        super().__init__()
        self.config = config

        # --- Проект CapCut ---
        self.project_name = QLineEdit(config.capcut_project_name)
        self.project_name.setPlaceholderText("Имя проекта, как в списке проектов CapCut")
        self.drafts_dir = QLineEdit(config.capcut_drafts_dir)
        self.drafts_dir.setPlaceholderText(
            r"Пусто = определить автоматически (…\CapCut\User Data\Projects\com.lveditor.draft)"
        )

        project_box = QGroupBox("Проект CapCut")
        project_form = QFormLayout(project_box)
        project_form.addRow("Имя проекта:", self.project_name)
        project_form.addRow("Папка проектов:", self.drafts_dir)

        # --- Субтитры (относительно исходного проекта) ---
        self.sub_offset = QDoubleSpinBox()
        self.sub_offset.setRange(-100.0, 100.0)
        self.sub_offset.setSuffix(" %")
        self.sub_offset.setValue(config.subtitles.vertical_offset_percent)
        self.sub_offset.setToolTip("Сдвиг по вертикали: + ниже, - выше. 0 = как в проекте.")

        self.sub_scale = QDoubleSpinBox()
        self.sub_scale.setRange(10.0, 400.0)
        self.sub_scale.setSuffix(" %")
        self.sub_scale.setValue(config.subtitles.scale_percent)
        self.sub_scale.setToolTip("Масштаб относительно исходного. 100 = как в проекте.")

        subs_box = QGroupBox("Субтитры")
        subs_form = QFormLayout(subs_box)
        subs_form.addRow("Смещение по вертикали:", self.sub_offset)
        subs_form.addRow("Масштаб:", self.sub_scale)
        subs_form.addRow(QLabel("Шрифт: случайный из тех, что начинаются на «Блок». "
                                "Стиль без чёрных краёв и шаблон берутся из проекта."))

        # --- Кнопки ---
        self.btn_save = QPushButton("Сохранить настройки")
        self.btn_save.clicked.connect(self._save)
        self.hint = QLabel(f"Данные и папки лежат рядом с софтом: {paths.app_dir()}")
        self.hint.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.addWidget(project_box)
        layout.addWidget(subs_box)
        layout.addWidget(self.btn_save)
        layout.addWidget(self.hint)
        layout.addStretch(1)

    def _save(self) -> None:
        self.config.capcut_project_name = self.project_name.text().strip()
        self.config.capcut_drafts_dir = self.drafts_dir.text().strip()
        self.config.subtitles.vertical_offset_percent = self.sub_offset.value()
        self.config.subtitles.scale_percent = self.sub_scale.value()
        try:
            self.config.save()
            QMessageBox.information(self, "Сохранено", "Настройки сохранены.")
        except OSError as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось сохранить конфиг:\n{e}")
