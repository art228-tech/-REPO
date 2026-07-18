"""Управление CapCut через интерфейс: запуск, открытие проекта, автосубтитры,
стиль/шрифт/шаблон субтитров, экспорт.

Все «что кликать» задаётся эталонными скриншотами кнопок в папке
«Интерфейс (скриншоты кнопок)». Это позволяет настроить автоматизацию под
конкретную сборку/тему CapCut без изменения кода. Список нужных скриншотов —
в REFERENCES ниже и в README.
"""

from __future__ import annotations

import os
import random
import subprocess
import time
from pathlib import Path

from ..logging_setup import get_logger
from .framework import Screen, UiError

logger = get_logger()

# role -> (имя файла, описание что заскриншотить)
REFERENCES: dict[str, tuple[str, str]] = {
    "project_tile": ("project_tile.png", "Плитка вашего проекта на главном экране CapCut"),
    "editor_ready": ("editor_ready.png", "Любой заметный элемент, когда редактор открыт (напр. кнопка «Экспорт»)"),
    "menu_text": ("menu_text.png", "Вкладка/кнопка «Текст» в верхнем меню"),
    "auto_captions": ("auto_captions.png", "Пункт «Автоматические субтитры»"),
    "captions_generate": ("captions_generate.png", "Кнопка запуска распознавания (напр. «Создать»/«Начать»)"),
    "captions_progress": ("captions_progress.png", "Индикатор процесса распознавания (чтобы дождаться конца)"),
    "batch_edit": ("batch_edit.png", "Кнопка пакетного редактирования субтитров (если есть)"),
    "template_button": ("template_button.png", "Вкладка «Шаблоны» в панели текста"),
    "template_target": ("template_target.png", "Нужный шаблон субтитров (миниатюра)"),
    "style_button": ("style_button.png", "Вкладка «Стиль» в панели текста"),
    "style_white": ("style_white.png", "Стиль без чёрных краёв (белый)"),
    "font_search": ("font_search.png", "Поле поиска шрифта"),
    "font_blok_1": ("font_blok_1.png", "1-й шрифт из списка на «Блок…»"),
    "font_blok_2": ("font_blok_2.png", "2-й шрифт на «Блок…» (если есть)"),
    "font_blok_3": ("font_blok_3.png", "3-й шрифт на «Блок…» (если есть)"),
    "export_button": ("export_button.png", "Кнопка «Экспорт» в редакторе"),
    "export_name_field": ("export_name_field.png", "Поле имени файла в окне экспорта"),
    "export_resolution": ("export_resolution.png", "Выпадающий список разрешения"),
    "export_res_1080": ("export_res_1080.png", "Пункт «1080p»"),
    "export_fps": ("export_fps.png", "Выпадающий список частоты кадров"),
    "export_fps_60": ("export_fps_60.png", "Пункт «60»"),
    "export_bitrate": ("export_bitrate.png", "Выпадающий список битрейта"),
    "export_bitrate_high": ("export_bitrate_high.png", "Пункт «Выше»"),
    "export_confirm": ("export_confirm.png", "Кнопка запуска экспорта в окне экспорта"),
    "export_progress": ("export_progress.png", "Индикатор процесса экспорта"),
}

FONT_ROLES = ["font_blok_1", "font_blok_2", "font_blok_3"]


def missing_references(references_dir: Path) -> list[str]:
    """Возвращает список отсутствующих обязательных скриншотов (кроме опциональных)."""
    optional = {"batch_edit", "captions_progress", "export_progress",
                "font_blok_2", "font_blok_3", "editor_ready"}
    missing = []
    for role, (fname, _desc) in REFERENCES.items():
        if role in optional:
            continue
        if not (references_dir / fname).exists():
            missing.append(fname)
    return missing


def find_capcut_exe(explicit: str = "") -> Path:
    """Ищет CapCut.exe. Сначала явный путь, затем типичные места установки."""
    if explicit:
        p = Path(explicit)
        if p.exists():
            return p
    local = os.environ.get("LOCALAPPDATA", "")
    candidates = []
    if local:
        candidates.append(Path(local) / "Programs" / "CapCut" / "CapCut.exe")
        apps = Path(local) / "CapCut" / "Apps"
        if apps.exists():
            # Берём самую свежую версию из подпапок.
            for sub in sorted(apps.iterdir(), reverse=True):
                candidates.append(sub / "CapCut.exe")
    for c in candidates:
        if c.exists():
            return c
    raise UiError("Не найден CapCut.exe. Укажите путь к нему в настройках.")


class CapCutController:
    def __init__(self, screen: Screen, exe_path: str = "") -> None:
        self.s = screen
        self.exe_path = exe_path

    # ---- запуск и фокус ----

    def launch(self) -> None:
        exe = find_capcut_exe(self.exe_path)
        logger.info("Запускаю CapCut: %s", exe)
        try:
            subprocess.Popen([str(exe)])
        except OSError as e:
            raise UiError(f"Не удалось запустить CapCut: {e}") from e
        time.sleep(6.0)

    def focus_window(self) -> bool:
        try:
            import pygetwindow as gw  # type: ignore
        except Exception:  # noqa: BLE001
            return False
        wins = [w for w in gw.getAllTitles() if "capcut" in w.lower()]
        if not wins:
            return False
        try:
            win = gw.getWindowsWithTitle(wins[0])[0]
            if win.isMinimized:
                win.restore()
            win.activate()
            try:
                win.maximize()
            except Exception:  # noqa: BLE001
                pass
            time.sleep(1.0)
            return True
        except Exception as e:  # noqa: BLE001
            logger.warning("Не удалось активировать окно CapCut: %s", e)
            return False

    # ---- шаги ----

    def open_project(self, project_name: str = "") -> None:
        logger.info("Шаг: открываю проект в CapCut…")
        self.launch()
        self.focus_window()
        # Двойной клик по плитке проекта на главном экране.
        self.s.double_click("project_tile", timeout=60)
        time.sleep(3.0)
        if self.s.exists("editor_ready", timeout=30):
            logger.info("Редактор открыт.")
        else:
            logger.info("Проект открыт (индикатор редактора не задан).")

    def generate_captions(self) -> None:
        logger.info("Шаг: автосубтитры (распознавание речи)…")
        self.s.click("menu_text", timeout=30)
        self.s.click("auto_captions", timeout=20)
        self.s.click("captions_generate", timeout=20)
        # Ждём завершения распознавания.
        if self.s.exists("captions_progress", timeout=8):
            self.s.wait_vanish("captions_progress", timeout=600)
        else:
            logger.info("Индикатор прогресса не задан — жду фиксированную паузу.")
            time.sleep(20)
        logger.info("Субтитры сгенерированы.")

    def apply_caption_style(self, font_rng: random.Random | None = None) -> None:
        logger.info("Шаг: стиль/шрифт/шаблон субтитров…")
        rng = font_rng or random
        # Пакетное редактирование всех субтитров, если есть такая кнопка.
        if self.s.exists("batch_edit", timeout=3):
            self.s.click("batch_edit")
        # Шаблон.
        self.s.click("template_button", timeout=20)
        self.s.click("template_target", timeout=20)
        # Стиль без чёрных краёв.
        self.s.click("style_button", timeout=20)
        self.s.click("style_white", timeout=20)
        # Случайный шрифт из доступных «Блок…».
        available = [r for r in FONT_ROLES
                     if (self.s.references_dir / REFERENCES[r][0]).exists()]
        if available:
            self.s.click("font_search", timeout=20)
            self.s.hotkey("ctrl", "a")
            self.s.type_text("Блок")
            time.sleep(1.0)
            chosen = rng.choice(available)
            self.s.click(chosen, timeout=15)
            logger.info("Выбран шрифт: %s", REFERENCES[chosen][0])
        else:
            logger.warning("Нет скриншотов шрифтов «Блок» — шаг шрифта пропущен.")

    def save_project(self) -> None:
        self.s.hotkey("ctrl", "s")
        time.sleep(1.5)
        logger.info("Проект сохранён (Ctrl+S).")

    def export(self, filename: str, resolution: str, fps: int, bitrate: str) -> None:
        logger.info("Шаг: экспорт (%s / %dfps / битрейт %s)…", resolution, fps, bitrate)
        self.s.click("export_button", timeout=30)
        time.sleep(2.0)
        # Имя файла.
        if self.s.exists("export_name_field", timeout=10):
            self.s.click("export_name_field")
            self.s.hotkey("ctrl", "a")
            self.s.type_text(filename)
        # Разрешение / FPS / битрейт.
        self._select("export_resolution", "export_res_1080")
        self._select("export_fps", "export_fps_60")
        self._select("export_bitrate", "export_bitrate_high")
        # Запуск экспорта.
        self.s.click("export_confirm", timeout=15)
        if self.s.exists("export_progress", timeout=10):
            self.s.wait_vanish("export_progress", timeout=1800)
        else:
            logger.info("Индикатор экспорта не задан — жду фиксированную паузу.")
            time.sleep(60)
        logger.info("Экспорт завершён: %s", filename)

    def _select(self, dropdown_ref: str, option_ref: str) -> None:
        try:
            self.s.click(dropdown_ref, timeout=8)
            time.sleep(0.5)
            self.s.click(option_ref, timeout=8)
        except UiError as e:
            logger.warning("Пропускаю выбор %s: %s", option_ref, e)
