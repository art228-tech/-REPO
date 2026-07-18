"""Вкладка «Настройки»: имя проекта, папки, проценты субтитров, экспорт."""

from __future__ import annotations

from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..assets import AssetManager
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

        # --- Папки ---
        folders_box = QGroupBox("Папки с файлами")
        self.btn_open_assets = QPushButton("Открыть папку «Ассеты» (сюда класть файлы)")
        self.btn_open_result = QPushButton("Открыть папку «Результат»")
        self.btn_open_assets.clicked.connect(self._open_assets)
        self.btn_open_result.clicked.connect(self._open_result)
        folders_row = QHBoxLayout(folders_box)
        folders_row.addWidget(self.btn_open_assets)
        folders_row.addWidget(self.btn_open_result)

        # --- UI-автоматизация (автосубтитры + экспорт) ---
        ui_box = QGroupBox("Автосубтитры и экспорт (интерфейс CapCut)")
        ui_form = QFormLayout(ui_box)
        self.ui_enabled = QCheckBox("Включить автосубтитры и экспорт")
        self.ui_enabled.setChecked(config.ui.enabled)
        self.ui_enabled.setToolTip(
            "Включайте только после того, как положите скриншоты кнопок CapCut "
            "в папку «Интерфейс (скриншоты кнопок)»."
        )
        self.capcut_exe = QLineEdit(config.ui.capcut_exe)
        self.capcut_exe.setPlaceholderText("Пусто = найти CapCut.exe автоматически")
        self.btn_open_refs = QPushButton("Открыть папку со скриншотами кнопок")
        self.btn_open_refs.clicked.connect(self._open_refs)
        ui_form.addRow(self.ui_enabled)
        ui_form.addRow("CapCut.exe:", self.capcut_exe)
        ui_form.addRow(self.btn_open_refs)

        # --- Кнопки ---
        self.btn_save = QPushButton("Сохранить настройки")
        self.btn_save.clicked.connect(self._save)
        self.hint = QLabel(f"Данные и папки лежат рядом с софтом: {paths.app_dir()}")
        self.hint.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.addWidget(project_box)
        layout.addWidget(subs_box)
        layout.addWidget(folders_box)
        layout.addWidget(ui_box)
        layout.addWidget(self.btn_save)
        layout.addWidget(self.hint)
        layout.addStretch(1)

    def _open_folder(self, path) -> None:
        try:
            AssetManager(paths.assets_dir()).ensure_folders()
        except OSError:
            pass
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _open_assets(self) -> None:
        self._open_folder(paths.assets_dir())

    def _open_result(self) -> None:
        self._open_folder(AssetManager(paths.assets_dir()).result_path())

    def _open_refs(self) -> None:
        refs = paths.references_dir()
        refs.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(refs)))

    def _save(self) -> None:
        self.config.capcut_project_name = self.project_name.text().strip()
        self.config.capcut_drafts_dir = self.drafts_dir.text().strip()
        self.config.subtitles.vertical_offset_percent = self.sub_offset.value()
        self.config.subtitles.scale_percent = self.sub_scale.value()
        self.config.ui.enabled = self.ui_enabled.isChecked()
        self.config.ui.capcut_exe = self.capcut_exe.text().strip()
        try:
            self.config.save()
            QMessageBox.information(self, "Сохранено", "Настройки сохранены.")
        except OSError as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось сохранить конфиг:\n{e}")
