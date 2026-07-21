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

# Координаты кнопок как ДОЛИ от размера экрана (последний запасной способ, если
# не сработали ни OCR по тексту, ни поиск по картинке). Сняты по интерфейсу
# CapCut 9.0 (русский), развёрнутое окно. Доли не зависят от разрешения.
COORD_FRAC = {
    "menu_captions": (0.258, 0.065),   # «Субтитры» в верхнем меню
    "export_button": (0.955, 0.020),   # «Экспорт» справа вверху
    "captions_generate": (0.86, 0.60), # зелёная «Создать» в панели субтитров
}

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


def close_capcut_process(exe_path: str = "") -> None:
    """Закрывает CapCut (taskkill), чтобы правка draft-файла не была затёрта
    уже открытым редактором. Безопасно вызывать, даже если CapCut не запущен."""
    exe_name = "CapCut.exe"
    try:
        exe_name = find_capcut_exe(exe_path).name
    except UiError:
        pass
    try:
        subprocess.run(["taskkill", "/IM", exe_name, "/F", "/T"],
                       capture_output=True, timeout=30)
    except Exception:  # noqa: BLE001
        pass
    time.sleep(3.0)


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

    # ---- области экрана (доли от размера экрана, разрешение-независимо) ----

    def _screen_size(self) -> tuple[int, int]:
        try:
            sz = self.s.pg.size()
            return int(sz.width), int(sz.height)
        except Exception:  # noqa: BLE001
            return 1920, 1080

    def region_top_menu(self):
        w, h = self._screen_size()
        return (0, 0, w, int(h * 0.09))

    def region_top_right(self):
        w, h = self._screen_size()
        return (int(w * 0.60), 0, int(w * 0.40), int(h * 0.09))

    def region_right_panel(self):
        w, h = self._screen_size()
        return (int(w * 0.66), int(h * 0.05), int(w * 0.34), int(h * 0.9))

    # ---- шаги ----

    def _in_editor(self, timeout: float = 5.0) -> bool:
        """Мы в редакторе, если в верхнем меню виден текст «Субтитры»/«Текст»."""
        return self.s.text_exists(["Субтитры", "Текст", "Эффекты"],
                                  region=self.region_top_menu(), timeout=timeout)

    def open_project(self, project_name: str = "") -> None:
        logger.info("Шаг: открываю проект в CapCut…")
        self.minimize_own_window()
        self.launch()
        self.focus_window()
        time.sleep(1.5)

        # Если проект уже открыт в редакторе — ничего не делаем.
        if self._in_editor(timeout=6):
            logger.info("Проект уже открыт в редакторе.")
            return

        # Ждём главный экран: кнопка «Создать проект» (по тексту — надёжно).
        if self.s.ocr_available():
            if self.s.text_exists(["Создать проект", "Новый проект", "Create project"],
                                  timeout=40):
                logger.info("Главный экран CapCut открыт.")
            else:
                logger.warning("Не вижу «Создать проект» — возможно, другой экран.")
        elif self.s.exists("home_create", timeout=40):
            logger.info("Главный экран CapCut открыт (по картинке).")

        # Открываем проект по НАЗВАНИЮ (текст плитки) — кликаем по превью над ним.
        opened = False
        name = project_name or "тестовик"
        if self.s.ocr_available():
            try:
                x, y = self.s.find_text([name], timeout=12, min_score=0.6)
                # превью — над подписью; двойной клик по превью открывает проект
                self.s.pg.doubleClick(x, y + PROJECT_TILE_DY)
                logger.info("Открываю проект «%s»: двойной клик по превью (%d, %d).",
                            name, x, y + PROJECT_TILE_DY)
                opened = True
            except UiError:
                logger.warning("Название проекта не распознано текстом.")
        if not opened:
            try:
                x, y = self.s.locate("project_tile", timeout=8, confidence=0.7)
                self.s.pg.doubleClick(x, y + PROJECT_TILE_DY)
                opened = True
            except UiError:
                fx, fy = FIRST_TILE_XY
                logger.warning("Открываю первую плитку по координатам (%d, %d).", fx, fy)
                self.s.pg.doubleClick(fx, fy)

        # Ждём, пока откроется редактор (появится верхнее меню).
        for _ in range(6):
            time.sleep(3.0)
            if self._in_editor(timeout=3):
                logger.info("Проект открыт — редактор загружен.")
                return
        logger.warning("Редактор не подтверждён по меню — продолжаю, надеясь на лучшее.")

    def generate_captions(self) -> None:
        logger.info("Шаг: автосубтитры (распознавание речи)…")
        self.s.capture("before_captions")

        # 1) Кнопка «Субтитры» в верхнем меню. Несколько способов + проверка,
        #    что открылась панель субтитров (виден язык/«Создать»/«Автоматические»).
        def captions_panel_open():
            return self.s.text_exists(
                ["Создать", "Автоматические субтитры", "Язык", "Русский",
                 "Распознавание"], timeout=4, min_score=0.6)

        if not self._click_button("menu_captions", texts=["Субтитры", "Субтитр"],
                                  ref="menu_captions", region=self.region_top_menu(),
                                  timeout=30, verify=captions_panel_open,
                                  verify_timeout=8):
            raise UiError("Не удалось открыть «Субтитры» ни одним способом "
                          "(OCR/картинка/координаты). См. скриншоты в logs/screenshots.")
        time.sleep(1.2)

        # 2) Иногда нужно выбрать под-пункт «Автоматические субтитры».
        if self.s.ocr_available() and self.s.text_exists(
                ["Автоматические субтитры", "Авто субтитры"], timeout=3):
            self.s.click_text(["Автоматические субтитры", "Авто субтитры"], timeout=5)
            time.sleep(1.0)

        # 3) Зелёная «Создать» (запуск распознавания). Язык «Русский» по умолчанию.
        def captions_started():
            return (self.s.text_exists(["Генерация", "Распознавание", "%", "Отмена"],
                                       timeout=4, min_score=0.6)
                    or not self.s.text_exists(["Создать"], timeout=2, min_score=0.7))

        if not self._click_button("captions_generate", texts=["Создать", "Начать"],
                                  ref="captions_generate", timeout=20,
                                  verify=captions_started, verify_timeout=6):
            raise UiError("Не удалось нажать «Создать» для запуска субтитров.")

        # 4) Ждём завершения распознавания.
        self.s.capture("captions_running")
        if self.s.has_ref("captions_progress") and self.s.exists("captions_progress", timeout=8):
            self.s.wait_vanish("captions_progress", timeout=600)
        elif self.s.ocr_available() and self.s.text_exists(
                ["Генерация", "Распознавание", "%"], timeout=8):
            self.s.wait_text_vanish(["Генерация", "Распознавание"], timeout=600)
        else:
            logger.info("Индикатор прогресса не виден — жду фиксированную паузу 30с.")
            time.sleep(30)
        time.sleep(2.0)
        self.s.capture("after_captions")
        logger.info("Субтитры сгенерированы.")

    def _click_text_or_ref(self, texts, ref: str, region=None,
                           timeout: float = 20.0, min_score: float = 0.68) -> bool:
        """Совместимость: обёртка над мультистратегийным кликом."""
        return self._click_button(ref, texts=texts, ref=ref, region=region,
                                   timeout=timeout, min_score=min_score)

    def _click_button(self, name: str, texts=None, ref: str | None = None,
                      region=None, timeout: float = 20.0, min_score: float = 0.68,
                      coord_key: str | None = None, verify=None,
                      verify_timeout: float = 6.0, double: bool = False) -> bool:
        """Пробует НЕСКОЛЬКО способов нажать кнопку и берёт первый рабочий:
          1) по тексту (OCR);
          2) по картинке-эталону;
          3) по координатам (доли экрана).
        Если задан `verify` — после клика проверяет, что нужный результат
        появился (например, открылась панель). Если результата нет — пробует
        следующий способ. Так один сбой не останавливает работу.

        Возвращает True, если клик подтверждён (или verify не задан, но способ
        отработал)."""
        strategies: list[tuple[str, callable]] = []
        if texts and self.s.ocr_available():
            strategies.append(("текст(OCR)",
                               lambda: self._do_click_text(texts, region, min_score, timeout, double)))
        if ref and self.s.has_ref(ref):
            strategies.append(("картинка",
                               lambda: self._do_click_ref(ref, min(timeout, 15), double)))
        ck = coord_key or (name if name in COORD_FRAC else None)
        if ck and ck in COORD_FRAC:
            strategies.append(("координаты", lambda: self._do_click_frac(COORD_FRAC[ck], double)))

        if not strategies:
            logger.warning("Кнопка «%s»: нет ни одного способа нажать (нет OCR/эталона/координат).", name)
            return False

        # Без OCR проверить результат по тексту нельзя — тогда считаем клик
        # выполненным (иначе рабочий способ будет ошибочно отброшен).
        use_verify = verify if self.s.ocr_available() else None

        for label, action in strategies:
            try:
                clicked = action()
            except UiError:
                clicked = False
            if not clicked:
                logger.info("Кнопка «%s»: способ [%s] не нашёл цель.", name, label)
                continue
            if use_verify is None:
                logger.info("Кнопка «%s»: нажата способом [%s].", name, label)
                return True
            if self._verify(use_verify, verify_timeout):
                logger.info("Кнопка «%s»: сработал способ [%s] (результат подтверждён).", name, label)
                return True
            logger.info("Кнопка «%s»: способ [%s] не дал результата — пробую следующий.", name, label)
        logger.warning("Кнопка «%s»: ни один способ не сработал.", name)
        return False

    def _verify(self, verify, timeout: float) -> bool:
        try:
            return bool(verify())
        except Exception:  # noqa: BLE001
            return False

    def _do_click_text(self, texts, region, min_score, timeout, double) -> bool:
        try:
            x, y = self.s.find_text(texts, region=region, min_score=min_score, timeout=timeout)
        except UiError:
            return False
        self.s.pg.click(x, y, clicks=2 if double else 1)
        return True

    def _do_click_ref(self, ref, timeout, double) -> bool:
        try:
            x, y = self.s.locate(ref, timeout=timeout, confidence=0.7)
        except UiError:
            return False
        self.s.pg.click(x, y, clicks=2 if double else 1)
        return True

    def _do_click_frac(self, frac, double) -> bool:
        w, h = self._screen_size()
        x, y = int(w * frac[0]), int(h * frac[1])
        logger.info("Клик по координатам-долям %.3f×%.3f → (%d, %d).", frac[0], frac[1], x, y)
        self.s.pg.click(x, y, clicks=2 if double else 1)
        return True

    def apply_caption_style(self, font_rng: random.Random | None = None) -> None:
        logger.info("Шаг: шрифт → стиль → шаблон…")
        rng = font_rng or random
        panel = self.region_right_panel()

        # Выделяем субтитр, чтобы справа открылась панель свойств текста.
        self._select_first_subtitle()

        # Вкладка «Основн.» (по тексту, фолбэк на картинку).
        self._click_text_or_ref(["Основн", "Основные"], "tab_basic",
                                region=panel, timeout=15)
        time.sleep(0.6)

        # Шрифт: открыть список «Шрифт», найти «блок», выбрать один из трёх.
        self._choose_font(rng, panel)

        # Стиль без чёрных краёв (белый пресет — иконка, без подписи).
        self._choose_white_style(panel)

        # Шаблон из «Избранного» (под-вкладка «Шаблоны»).
        self._click_text_or_ref(["Шаблоны", "Шаблон"], "tab_template",
                                region=panel, timeout=15)
        time.sleep(0.8)
        if self.s.has_ref("template_favorite"):
            try:
                self.s.click("template_favorite", timeout=12)
                logger.info("Применён шаблон из «Избранного».")
            except UiError:
                logger.warning("Шаблон из «Избранного» не найден по картинке — пропущен.")
        else:
            logger.warning("Нет эталона шаблона (template_favorite) — шаг шаблона пропущен.")
        time.sleep(1.0)
        self.s.capture("after_style")

    def _select_first_subtitle(self) -> None:
        """Кликает по первому субтитру на текст-дорожке, чтобы открыть его
        свойства. Субтитр в самом начале ролика у левого края таймлайна."""
        w, h = self._screen_size()
        # Текст-дорожка обычно верхняя среди дорожек; кликаем ближе к началу.
        x = int(w * 0.11)
        y = int(h * 0.66)
        try:
            self.s.pg.click(x, y)
            time.sleep(0.6)
        except Exception:  # noqa: BLE001
            pass

    def _choose_font(self, rng, panel) -> None:
        available = [r for r in FONT_ROLES if self.s.has_ref(REFERENCES[r][0])]
        # Открываем поле «Шрифт».
        if not self._click_text_or_ref(["Шрифт"], "font_dropdown", region=panel, timeout=12):
            logger.warning("Поле «Шрифт» не найдено — шаг шрифта пропущен.")
            return
        time.sleep(0.8)
        # Поле поиска шрифта.
        if not self._click_text_or_ref(["Поиск", "Search"], "font_search",
                                       region=panel, timeout=8):
            logger.info("Поле поиска шрифта не найдено — пробую печатать сразу.")
        self.s.hotkey("ctrl", "a")
        self.s.type_text("блок")  # ввод кириллицы через буфер обмена
        time.sleep(1.3)
        # Выбор одного из шрифтов «Блок». Сначала пробуем по тексту.
        variants = [["Блок-hv", "Блок hv"], ["Блок-Rg", "Блок Rg"], ["Блоки", "Блок"]]
        idx = rng.randrange(len(variants))
        if self.s.ocr_available():
            try:
                self.s.click_text(variants[idx], region=panel, timeout=8, min_score=0.6)
                logger.info("Выбран шрифт: %s", variants[idx][0])
                self.s.press("escape")
                time.sleep(0.4)
                return
            except UiError:
                logger.info("Шрифт %s не распознан текстом — пробую картинку.", variants[idx][0])
        if available:
            chosen = rng.choice(available)
            try:
                self.s.click(chosen, timeout=10)
                logger.info("Выбран шрифт по картинке: %s", REFERENCES[chosen][0])
            except UiError:
                logger.warning("Шрифт не выбран (нет совпадения).")
        else:
            logger.warning("Шрифт «Блок» не выбран — ни текст, ни картинки не подошли.")
        self.s.press("escape")
        time.sleep(0.4)

    def _choose_white_style(self, panel) -> None:
        """Белый пресет без чёрных краёв. Это иконка без подписи, поэтому
        ищем якорь ⊘ («без стиля») и кликаем правее (первый белый пресет)."""
        if not self.s.has_ref("style_none"):
            logger.warning("Нет эталона ⊘ (style_none) — стиль без краёв пропущен.")
            return
        try:
            sx, sy = PANEL_SCROLL_XY
            x, y = self.s.locate_scrolling("style_none", sx, sy, step=-400, attempts=6)
            self.s.pg.click(x + STYLE_WHITE_DX, y)
            logger.info("Выбран белый стиль без чёрных краёв (⊘+%d).", STYLE_WHITE_DX)
            time.sleep(0.5)
        except UiError:
            logger.warning("Пресет стиля не найден — стиль без краёв пропущен.")

    def save_project(self) -> None:
        self.s.hotkey("ctrl", "s")
        time.sleep(1.5)
        logger.info("Проект сохранён (Ctrl+S).")

    def export(self, filename: str, resolution: str, fps: int, bitrate: str) -> None:
        logger.info("Шаг: экспорт (%s / %dfps / битрейт %s)…", resolution, fps, bitrate)
        # Кнопка «Экспорт» справа вверху. Несколько способов + проверка, что
        # открылось окно экспорта (виден «Имя»/«Разрешение»/«Частота кадров»).
        def export_dialog_open():
            return self.s.text_exists(
                ["Имя", "Название", "Разрешение", "Частота кадров", "Экспортировать в"],
                timeout=4, min_score=0.6)

        if not self._click_button("export_button", texts=["Экспорт", "Export"],
                                  ref="export_button", region=self.region_top_right(),
                                  timeout=30, coord_key="export_button",
                                  verify=export_dialog_open, verify_timeout=8):
            raise UiError("Не удалось открыть окно экспорта ни одним способом.")
        time.sleep(2.0)
        self.s.capture("export_dialog")

        # Имя файла: кликаем в поле правее метки «Имя»/«Название».
        named = False
        if self.s.ocr_available():
            try:
                self.s.click_text(["Имя", "Название"], timeout=10, dx=NAME_FIELD_DX)
                named = True
            except UiError:
                pass
        if not named and self.s.has_ref("export_name_label"):
            try:
                self.s.click("export_name_label", timeout=10, dx=NAME_FIELD_DX)
                named = True
            except UiError:
                pass
        if named:
            self.s.hotkey("ctrl", "a")
            self.s.type_text(filename)
            time.sleep(0.3)
        else:
            logger.warning("Поле имени файла не найдено — экспорт с именем по умолчанию.")

        # Разрешение/битрейт: обычно уже 1080P / «Выше». Ставим по тексту/эталону.
        self._select_dropdown(["Разрешение"], "1080P", "export_resolution", "export_res_1080")
        self._select_dropdown(["Битрейт", "Скорость передачи"], "Выше",
                              "export_bitrate", "export_bitrate_high")
        # Частота кадров -> 60fps.
        self._select_dropdown(["Частота кадров", "Кадр"], "60fps",
                              "export_fps", "export_fps_60")

        # Запуск экспорта (зелёная кнопка «Экспорт» в самом окне).
        if not self._click_text_or_ref(["Экспорт", "Export"], "export_confirm", timeout=15):
            raise UiError("Не найдена кнопка запуска экспорта в окне.")
        # Ждём завершения.
        if self.s.has_ref("export_progress") and self.s.exists("export_progress", timeout=10):
            self.s.wait_vanish("export_progress", timeout=1800)
        elif self.s.ocr_available() and self.s.text_exists(
                ["Экспорт завершён", "Успешно", "Готово", "Открыть папку"], timeout=1800):
            logger.info("Экспорт завершён (подтверждён по тексту).")
        else:
            logger.info("Индикатор экспорта не задан — жду фиксированную паузу.")
            time.sleep(90)
        time.sleep(2.0)
        logger.info("Экспорт завершён: %s", filename)

    def _select_dropdown(self, dropdown_texts, option_text: str,
                         dropdown_ref: str, option_ref: str) -> None:
        """Выбирает пункт `option_text` в выпадающем списке. Сначала проверяет,
        не выбран ли он уже (тогда ничего не делаем); иначе открывает список
        (по подписи/эталону) и кликает по пункту (по тексту/эталону)."""
        panel = self.region_top_right() if False else None  # окно экспорта — весь экран
        # Уже выбран? (текст пункта виден на экране)
        if self.s.ocr_available() and self.s.text_exists([option_text], timeout=1, min_score=0.75):
            # видно и без раскрытия — но это может быть и сам список. Всё равно попробуем.
            pass
        # Открыть список.
        opened = self._click_text_or_ref(dropdown_texts, dropdown_ref, timeout=6, min_score=0.7)
        if not opened:
            logger.info("Список %s не найден — пропускаю (возможно, уже задан).", dropdown_texts[0])
            return
        time.sleep(0.6)
        # Выбрать пункт.
        if self.s.ocr_available():
            try:
                self.s.click_text([option_text], timeout=6, min_score=0.7)
                logger.info("Выбрано: %s", option_text)
                time.sleep(0.4)
                return
            except UiError:
                pass
        if self.s.has_ref(option_ref):
            try:
                self.s.click(option_ref, timeout=6)
                logger.info("Выбрано по картинке: %s", option_text)
            except UiError:
                logger.warning("Пункт %s не найден — оставляю как есть.", option_text)
        else:
            logger.warning("Пункт %s не выбран (нет текста/эталона).", option_text)
