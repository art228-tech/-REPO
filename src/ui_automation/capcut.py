"""Управление CapCut через интерфейс (калибровано по скриншотам пользователя).

Реальный процесс (CapCut 9.0.0, русский интерфейс):
  1. Главный экран → двойной клик по плитке проекта.
  2. Верхнее меню «Субтитры» → язык «Русский» (по умолчанию) → зелёная «Создать».
  3. Дождаться окна «Генерация субтитров… %».
  4. Панель справа «Текст», галочка «Применить ко всем» (вкл. по умолчанию):
       - вкладка «Основн.»: выбрать ШРИФТ (поиск «блок» → один из Блок-hv/Rg/Блоки);
       - выбрать СТИЛЬ без чёрных краёв (белый пресет в «Стиль по пресету»);
       - вкладка «Шаблоны»: выбрать ШАБЛОН из «Избранное»;
       - (опционально) «Трансформация»: масштаб/позиция.
  5. Ctrl+S.
  6. «Экспорт» (справа вверху) → имя файла → 1080P (по умолч.) → битрейт «Выше»
     (по умолч.) → частота кадров 60fps → зелёная «Экспорт» → дождаться конца.

Порядок и все «что кликать» задаются эталонными скриншотами кнопок в папке
«Интерфейс (скриншоты кнопок)».
"""

from __future__ import annotations

import os
import random
import shutil
import subprocess
import time
from pathlib import Path

from ..logging_setup import get_logger
from .framework import Screen, UiError

logger = get_logger()

# Точка прокрутки правой панели (в пределах панели свойств субтитров).
PANEL_SCROLL_XY = (1690, 250)
# Смещение от ⊘ («без стиля») до первого белого пресета «Aa» без чёрных краёв.
STYLE_WHITE_DX = 50
# Смещение от метки «Имя» до поля ввода имени файла в окне экспорта.
NAME_FIELD_DX = 260
# Смещение от названия проекта вверх к превью (по превью и кликаем, чтобы открыть).
PROJECT_TILE_DY = -80
# Координаты центра превью первой плитки проекта на главном экране (1920x1080,
# развёрнутое окно CapCut). Запасной способ открыть проект, если поиск по
# названию не сработал.
FIRST_TILE_XY = (365, 725)

# role -> (имя файла, описание что заскриншотить)
REFERENCES: dict[str, tuple[str, str]] = {
    "home_create": ("home_create.png", "Кнопка «Создать проект» на главном экране — подтверждение главного экрана"),
    "project_tile": ("project_tile.png", "Название проекта на главном экране («тестовик») — по нему находим плитку"),
    "menu_captions": ("menu_captions.png", "Кнопка «Субтитры» в верхнем меню редактора"),
    "captions_generate": ("captions_generate.png", "Зелёная кнопка «Создать» (запуск распознавания)"),
    "captions_progress": ("captions_progress.png", "Окно «Генерация субтитров…» (для ожидания конца)"),
    "tab_basic": ("tab_basic.png", "Под-вкладка «Основн.» в панели текста"),
    "font_dropdown": ("font_dropdown.png", "Поле «Шрифт» (значение, напр. «Система»)"),
    "font_search": ("font_search.png", "Поле поиска шрифта («Поиск текста»)"),
    "font_blok_1": ("font_blok_1.png", "Шрифт «Блок-hv» в списке"),
    "font_blok_2": ("font_blok_2.png", "Шрифт «Блок-Rg» в списке"),
    "font_blok_3": ("font_blok_3.png", "Шрифт «Блоки» в списке"),
    "style_none": ("style_none.png", "Пресет «без стиля» (⊘) в «Стиль по пресету» — якорь"),
    "tab_template": ("tab_template.png", "Под-вкладка «Шаблоны» в панели текста"),
    "template_favorite": ("template_favorite.png", "Ваш шаблон в разделе «Избранное»"),
    "export_button": ("export_button.png", "Кнопка «Экспорт» справа вверху"),
    "export_name_label": ("export_name_label.png", "Метка «Имя» в окне экспорта — якорь"),
    "export_fps": ("export_fps.png", "Выпадающий список «Частота кадров»"),
    "export_fps_60": ("export_fps_60.png", "Пункт «60fps» в списке частоты кадров"),
    "export_confirm": ("export_confirm.png", "Зелёная кнопка «Экспорт» в окне экспорта"),
    "export_progress": ("export_progress.png", "Индикатор процесса экспорта (%)"),
    # опциональные — 1080P и «Выше» обычно стоят по умолчанию
    "export_resolution": ("export_resolution.png", "Список «Разрешение» (опц.)"),
    "export_res_1080": ("export_res_1080.png", "Пункт «1080P» (опц.)"),
    "export_bitrate": ("export_bitrate.png", "Список «Битрейт» (опц.)"),
    "export_bitrate_high": ("export_bitrate_high.png", "Пункт «Выше» (опц.)"),
}

FONT_ROLES = ["font_blok_1", "font_blok_2", "font_blok_3"]

# Обязательные эталоны (без них шаг не выполнить).
REQUIRED = [
    "project_tile", "menu_captions", "captions_generate",
    "tab_basic", "font_dropdown", "font_search", "font_blok_1",
    "style_none", "tab_template", "template_favorite",
    "export_button", "export_name_label", "export_fps", "export_fps_60",
    "export_confirm",
]


def missing_references(references_dir: Path, defaults_dir: Path | None = None) -> list[str]:
    """Отсутствующие обязательные эталоны (с учётом встроенных по умолчанию)."""
    missing = []
    for r in REQUIRED:
        fname = REFERENCES[r][0]
        if (references_dir / fname).exists():
            continue
        if defaults_dir and (defaults_dir / fname).exists():
            continue
        missing.append(fname)
    return missing


# Версия набора встроенных эталонов. При изменении — обновления перезапишут
# устаревшие копии в папке пользователя (иначе старые эталоны залипают).
REFS_VERSION = "3"


def ensure_references(references_dir: Path, defaults_dir: Path) -> None:
    """Копирует встроенные эталоны в папку пользователя. При смене версии набора
    перезаписывает их (чтобы применялись исправления), иначе — копирует только
    недостающие, сохраняя возможные правки пользователя."""
    references_dir.mkdir(parents=True, exist_ok=True)
    if not defaults_dir.exists():
        return
    marker = references_dir / ".refs_version"
    current = marker.read_text(encoding="utf-8").strip() if marker.exists() else ""
    overwrite = current != REFS_VERSION
    for src in defaults_dir.glob("*.png"):
        dst = references_dir / src.name
        if overwrite or not dst.exists():
            try:
                shutil.copy2(src, dst)
            except OSError as e:  # noqa: BLE001
                logger.warning("Не удалось скопировать эталон %s: %s", src.name, e)
    if overwrite:
        try:
            marker.write_text(REFS_VERSION, encoding="utf-8")
        except OSError:
            pass


def find_capcut_exe(explicit: str = "") -> Path:
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
        time.sleep(7.0)

    def minimize_own_window(self) -> None:
        """Сворачивает окно самого софта, чтобы оно не перекрывало CapCut."""
        try:
            import pygetwindow as gw  # type: ignore
        except Exception:  # noqa: BLE001
            return
        for t in list(gw.getAllTitles()):
            if "автомонтаж" in t.lower():
                try:
                    gw.getWindowsWithTitle(t)[0].minimize()
                except Exception:  # noqa: BLE001
                    pass

    def close(self) -> None:
        """Полностью закрывает CapCut и ждёт выхода процесса, чтобы draft-файл
        был освобождён и его можно было безопасно править извне."""
        logger.info("Шаг: закрываю CapCut (для правки субтитров в файле)…")
        exe_name = "CapCut.exe"
        try:
            exe_name = find_capcut_exe(self.exe_path).name
        except UiError:
            pass
        killed = False
        try:
            subprocess.run(["taskkill", "/IM", exe_name, "/F", "/T"],
                           capture_output=True, timeout=30)
            killed = True
        except Exception as e:  # noqa: BLE001
            logger.warning("taskkill не сработал (%s), пробую закрыть окно.", e)
        if not killed:
            try:
                import pygetwindow as gw  # type: ignore

                for t in list(gw.getAllTitles()):
                    if ("capcut" in t.lower() or "сарсut" in t.lower()) and "автомонтаж" not in t.lower():
                        gw.getWindowsWithTitle(t)[0].close()
            except Exception:  # noqa: BLE001
                pass
        # Ждём, пока процесс действительно завершится и отпустит файл.
        time.sleep(5.0)
        logger.info("CapCut закрыт.")

    def focus_window(self) -> bool:
        try:
            import pygetwindow as gw  # type: ignore
        except Exception:  # noqa: BLE001
            return False
        titles = [t for t in gw.getAllTitles()
                  if ("capcut" in t.lower() or "сарсut" in t.lower())
                  and "автомонтаж" not in t.lower()]
        if not titles:
            return False
        try:
            win = gw.getWindowsWithTitle(titles[0])[0]
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
        self.minimize_own_window()
        self.launch()
        self.focus_window()
        time.sleep(1.5)

        # Подтверждаем, что видим главный экран (кнопка «Создать проект»).
        if self.s.exists("home_create", timeout=40):
            logger.info("Главный экран CapCut открыт.")
        else:
            logger.warning("Не вижу кнопку «Создать проект» — возможно, другой экран.")

        # Основной способ: найти проект по названию и кликнуть по превью над ним.
        try:
            x, y = self.s.locate("project_tile", timeout=10, confidence=0.75)
            self.s.pg.doubleClick(x, y + PROJECT_TILE_DY)
            logger.info("Открываю проект по названию: двойной клик (%d, %d).", x, y + PROJECT_TILE_DY)
        except UiError:
            fx, fy = FIRST_TILE_XY
            logger.warning("Название не найдено — открываю первую плитку по координатам (%d, %d).", fx, fy)
            self.s.pg.doubleClick(fx, fy)
        time.sleep(5.0)
        logger.info("Проект открыт.")

    def generate_captions(self) -> None:
        logger.info("Шаг: автосубтитры (распознавание речи)…")
        self.s.capture("before_captions")
        self.s.click("menu_captions", timeout=30)
        time.sleep(1.0)
        # Язык «Русский» и вкладка «Автоматические субтитры» — по умолчанию.
        self.s.click("captions_generate", timeout=20)
        # Ждём завершения распознавания.
        if self.s.exists("captions_progress", timeout=8):
            self.s.wait_vanish("captions_progress", timeout=600)
        else:
            logger.info("Окно прогресса не задано — жду фиксированную паузу.")
            time.sleep(25)
        time.sleep(2.0)
        self.s.capture("after_captions")
        logger.info("Субтитры сгенерированы.")

    def apply_caption_style(self, font_rng: random.Random | None = None) -> None:
        logger.info("Шаг: шрифт → стиль → шаблон…")
        rng = font_rng or random

        # Вкладка «Основн.».
        self.s.click("tab_basic", timeout=20)
        time.sleep(0.5)

        # Шрифт: открыть список, найти «блок», выбрать случайный из доступных.
        available = [r for r in FONT_ROLES if self.s.has_ref(REFERENCES[r][0])]
        if available:
            self.s.click("font_dropdown", timeout=15)
            time.sleep(0.7)
            self.s.click("font_search", timeout=10)
            self.s.hotkey("ctrl", "a")
            self.s.type_text("блок")
            time.sleep(1.2)
            chosen = rng.choice(available)
            self.s.click(chosen, timeout=15)
            logger.info("Выбран шрифт: %s", REFERENCES[chosen][0])
            self.s.press("escape")
            time.sleep(0.5)
        else:
            logger.warning("Нет скриншотов шрифтов «Блок» — шаг шрифта пропущен.")

        # Стиль без чёрных краёв (белый пресет). Он ниже — прокручиваем панель
        # и кликаем по первому пресету справа от ⊘ («без стиля»).
        self.s.click("tab_basic", timeout=10)
        time.sleep(0.3)
        sx, sy = PANEL_SCROLL_XY
        x, y = self.s.locate_scrolling("style_none", sx, sy, step=-400, attempts=6)
        self.s.pg.click(x + STYLE_WHITE_DX, y)
        logger.info("Выбран белый стиль без чёрных краёв (⊘+%d).", STYLE_WHITE_DX)
        time.sleep(0.5)

        # Шаблон из «Избранного» (под-вкладка «Шаблоны» вверху панели).
        self.s.click("tab_template", timeout=15)
        time.sleep(0.6)
        self.s.click("template_favorite", timeout=15)
        logger.info("Применён шаблон из «Избранного».")
        time.sleep(1.0)
        self.s.capture("after_style")

    def save_project(self) -> None:
        self.s.hotkey("ctrl", "s")
        time.sleep(1.5)
        logger.info("Проект сохранён (Ctrl+S).")

    def export(self, filename: str, resolution: str, fps: int, bitrate: str) -> None:
        logger.info("Шаг: экспорт (%s / %dfps / битрейт %s)…", resolution, fps, bitrate)
        self.s.click("export_button", timeout=30)
        time.sleep(2.5)
        self.s.capture("export_dialog")
        # Имя файла: кликаем в поле правее метки «Имя».
        self.s.click("export_name_label", timeout=15, dx=NAME_FIELD_DX)
        self.s.hotkey("ctrl", "a")
        self.s.type_text(filename)
        time.sleep(0.3)
        # Разрешение и битрейт обычно уже 1080P / «Выше» — задаём, если есть эталоны.
        self._select_optional("export_resolution", "export_res_1080")
        self._select_optional("export_bitrate", "export_bitrate_high")
        # Частоту кадров меняем на 60.
        self._select("export_fps", "export_fps_60")
        # Запуск экспорта.
        self.s.click("export_confirm", timeout=15)
        # Ждём завершения.
        if self.s.exists("export_progress", timeout=10):
            self.s.wait_vanish("export_progress", timeout=1800)
        else:
            logger.info("Индикатор экспорта не задан — жду фиксированную паузу.")
            time.sleep(90)
        time.sleep(2.0)
        logger.info("Экспорт завершён: %s", filename)

    def _select(self, dropdown_ref: str, option_ref: str) -> None:
        self.s.click(dropdown_ref, timeout=10)
        time.sleep(0.6)
        self.s.click(option_ref, timeout=10)

    def _select_optional(self, dropdown_ref: str, option_ref: str) -> None:
        if not self.s.has_ref(REFERENCES[dropdown_ref][0]):
            return
        try:
            self._select(dropdown_ref, option_ref)
        except UiError as e:
            logger.warning("Пропускаю %s: %s", option_ref, e)
