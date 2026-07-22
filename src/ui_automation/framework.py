"""Базовые примитивы UI-автоматизации для CapCut (Windows).

Подход: клики по эталонным скриншотам кнопок (template matching), потому что
CapCut рисует интерфейс сам и не отдаёт кнопки в системное дерево элементов.
Пользователь один раз кладёт скриншоты кнопок в папку «Интерфейс (скриншоты
кнопок)», а автоматизация находит их на экране и кликает.

Все зависимости от экрана (pyautogui) импортируются лениво внутри методов,
чтобы модуль можно было импортировать и там, где нет графики (например, в CI).
Каждая ошибка сопровождается скриншотом экрана и понятным сообщением в лог.
"""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

from ..logging_setup import get_logger
from .ocr import OcrEngine, best_match

logger = get_logger()


class UiError(Exception):
    """Ошибка UI-автоматизации (не нашли элемент, таймаут и т.п.)."""


class Screen:
    def __init__(self, references_dir: Path, shots_dir: Path,
                 confidence: float = 0.85, default_timeout: float = 30.0,
                 defaults_dir: Path | None = None, use_ocr: bool = True) -> None:
        self.references_dir = Path(references_dir)
        self.defaults_dir = Path(defaults_dir) if defaults_dir else None
        self.shots_dir = Path(shots_dir)
        self.confidence = confidence
        self.default_timeout = default_timeout
        self.use_ocr = use_ocr
        self._pg = None
        self._ocr = OcrEngine()

    # ---- ленивый доступ к pyautogui ----

    @property
    def pg(self):
        if self._pg is None:
            try:
                import pyautogui  # type: ignore
            except Exception as e:  # noqa: BLE001
                raise UiError(
                    "Не удалось загрузить pyautogui. Установите зависимости "
                    f"(requirements.txt). Причина: {e}"
                ) from e
            pyautogui.FAILSAFE = True
            pyautogui.PAUSE = 0.15
            self._pg = pyautogui
        return self._pg

    # ---- скриншоты ----

    def capture(self, tag: str = "") -> Path:
        self.shots_dir.mkdir(parents=True, exist_ok=True)
        name = f"{datetime.now():%H-%M-%S}_{tag or 'shot'}.png"
        path = self.shots_dir / name
        try:
            self.pg.screenshot(str(path))
        except Exception as e:  # noqa: BLE001
            logger.warning("Не удалось сделать скриншот: %s", e)
        return path

    # ---- поиск эталонов ----

    def _ref_path(self, ref: str) -> Path:
        name = ref if ref.endswith(".png") else ref + ".png"
        user = self.references_dir / name
        if user.exists():
            return user
        if self.defaults_dir is not None:
            d = self.defaults_dir / name
            if d.exists():
                return d
        return user  # для понятной ошибки «нет скриншота»

    def has_ref(self, ref: str) -> bool:
        return self._ref_path(ref).exists()

    # Масштабы для многомасштабного поиска: эталон-скриншот не обязан идеально
    # совпадать по разрешению с экраном (другой монитор/масштаб/DPI).
    _SCALES = [1.0, 0.9, 1.1, 0.8, 1.2, 0.7, 1.3, 0.6, 0.5, 1.5]

    def _match_multiscale(self, ref_path: Path, conf: float):
        """Ищет эталон на экране в нескольких масштабах через OpenCV.
        Возвращает (x, y) центра лучшего совпадения или None."""
        try:
            import cv2  # type: ignore
            import numpy as np  # type: ignore
        except Exception:
            return self._match_pyautogui(ref_path, conf)

        shot = self.pg.screenshot()
        screen = cv2.cvtColor(np.array(shot), cv2.COLOR_RGB2GRAY)
        templ0 = cv2.imread(str(ref_path), cv2.IMREAD_GRAYSCALE)
        if templ0 is None:
            return None
        best_val, best_xy = -1.0, None
        sh, sw = screen.shape[:2]
        for scale in self._SCALES:
            tw = max(8, int(templ0.shape[1] * scale))
            th = max(8, int(templ0.shape[0] * scale))
            if tw >= sw or th >= sh:
                continue
            templ = cv2.resize(templ0, (tw, th), interpolation=cv2.INTER_AREA)
            res = cv2.matchTemplate(screen, templ, cv2.TM_CCOEFF_NORMED)
            _min, maxv, _minl, maxl = cv2.minMaxLoc(res)
            if maxv > best_val:
                best_val = maxv
                best_xy = (maxl[0] + tw // 2, maxl[1] + th // 2)
        if best_xy is not None and best_val >= conf:
            return best_xy
        return None

    def _match_pyautogui(self, ref_path: Path, conf: float):
        try:
            loc = self.pg.locateCenterOnScreen(str(ref_path), confidence=conf)
            return (int(loc.x), int(loc.y)) if loc is not None else None
        except Exception:  # noqa: BLE001
            return None

    def locate(self, ref: str, timeout: float | None = None,
               confidence: float | None = None):
        """Ждёт появления эталона на экране и возвращает его центр (x, y)."""
        ref_path = self._ref_path(ref)
        if not ref_path.exists():
            raise UiError(f"Нет скриншота кнопки: {ref_path.name} "
                          f"(положите его в «{self.references_dir.name}»)")
        timeout = self.default_timeout if timeout is None else timeout
        conf = self.confidence if confidence is None else confidence
        deadline = time.time() + timeout
        while time.time() < deadline:
            xy = self._match_multiscale(ref_path, conf)
            if xy is not None:
                return xy
            time.sleep(0.5)
        self.capture(f"not_found_{ref_path.stem}")
        raise UiError(
            f"Не нашёл на экране «{ref_path.name}» за {timeout:.0f}с. "
            f"Скриншот экрана сохранён в logs/screenshots. "
            f"Проверьте, что кнопка видна и скриншот-эталон актуален."
        )

    def exists(self, ref: str, timeout: float = 2.0,
               confidence: float | None = None) -> bool:
        try:
            self.locate(ref, timeout=timeout, confidence=confidence)
            return True
        except UiError:
            return False

    # ---- действия ----

    def click(self, ref: str, timeout: float | None = None,
              confidence: float | None = None, clicks: int = 1,
              dx: int = 0, dy: int = 0) -> None:
        x, y = self.locate(ref, timeout=timeout, confidence=confidence)
        self.pg.click(x + dx, y + dy, clicks=clicks)
        logger.info("Клик по «%s» в (%d, %d)%s", ref, x + dx, y + dy,
                    " x2" if clicks == 2 else "")

    def double_click(self, ref: str, **kw) -> None:
        self.click(ref, clicks=2, **kw)

    def click_xy(self, x: int, y: int) -> None:
        self.pg.click(x, y)

    def scroll(self, x: int, y: int, amount: int) -> None:
        """Прокрутка колесом в точке (x, y). amount<0 — вниз."""
        self.pg.moveTo(x, y)
        self.pg.scroll(amount)

    def locate_scrolling(self, ref: str, scroll_x: int, scroll_y: int,
                         step: int = -400, attempts: int = 6,
                         confidence: float | None = None):
        """Ищет эталон, при необходимости прокручивая панель (для элементов
        ниже видимой области, например пресетов стиля)."""
        for i in range(attempts):
            xy = self._match_multiscale(self._ref_path(ref),
                                        confidence or self.confidence)
            if xy is not None:
                return xy
            self.scroll(scroll_x, scroll_y, step)
            time.sleep(0.6)
        # финальная попытка со скриншотом ошибки
        return self.locate(ref, timeout=3, confidence=confidence)

    # ---- поиск по ТЕКСТУ (OCR) — основной, надёжный способ ----

    def ocr_available(self) -> bool:
        return self.use_ocr and self._ocr.available()

    def _ocr_boxes(self, region: tuple[int, int, int, int] | None = None):
        """OCR всего экрана (или области region=(left,top,w,h)). Координаты
        боксов возвращаются в СИСТЕМЕ ЭКРАНА (со смещением region)."""
        shot = self.pg.screenshot()
        left = top = 0
        if region is not None:
            left, top, w, h = region
            shot = shot.crop((left, top, left + w, top + h))
        boxes = self._ocr.read(shot)
        for b in boxes:
            b.cx += left
            b.cy += top
        return boxes

    def find_text(self, targets, region=None, min_score: float = 0.7,
                  timeout: float | None = None):
        """Ждёт, пока на экране появится текст из `targets`, и возвращает центр
        (x, y) лучшего совпадения. targets — строка или список строк-синонимов."""
        if isinstance(targets, str):
            targets = [targets]
        timeout = self.default_timeout if timeout is None else timeout
        deadline = time.time() + timeout
        last_boxes = []
        while time.time() < deadline:
            last_boxes = self._ocr_boxes(region)
            m = best_match(targets, last_boxes, min_score)
            if m is not None:
                box, sc = m
                logger.info("Текст %s найден: %r (score %.2f) в (%d, %d)",
                            targets[0], box.text, sc, int(box.cx), int(box.cy))
                return int(box.cx), int(box.cy)
            time.sleep(0.5)
        slug = "".join(ch for ch in targets[0].lower() if ch.isalnum())[:20] or "text"
        self.capture(f"text_not_found_{slug}")
        seen = ", ".join(sorted({b.text for b in last_boxes})[:25])
        raise UiError(
            f"Не нашёл на экране текст «{targets[0]}» за {timeout:.0f}с. "
            f"Скриншот в logs/screenshots. Распознано на экране: {seen or '—'}"
        )

    def text_exists(self, targets, region=None, min_score: float = 0.7,
                    timeout: float = 2.0) -> bool:
        try:
            self.find_text(targets, region=region, min_score=min_score, timeout=timeout)
            return True
        except UiError:
            return False

    def click_text(self, targets, region=None, min_score: float = 0.7,
                   timeout: float | None = None, dx: int = 0, dy: int = 0,
                   clicks: int = 1) -> tuple[int, int]:
        x, y = self.find_text(targets, region=region, min_score=min_score, timeout=timeout)
        self.pg.click(x + dx, y + dy, clicks=clicks)
        logger.info("Клик по тексту %s в (%d, %d)%s",
                    targets if isinstance(targets, str) else targets[0],
                    x + dx, y + dy, " x2" if clicks == 2 else "")
        return x, y

    def wait_text_vanish(self, targets, region=None, min_score: float = 0.7,
                         timeout: float = 600.0) -> None:
        """Ждёт, пока текст исчезнет (например, окно «Генерация субтитров…»)."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if not self.text_exists(targets, region=region, min_score=min_score, timeout=1.0):
                return
            time.sleep(1.5)
        logger.warning("Текст %s не исчез за %.0fс — продолжаю.", targets, timeout)

    def wait_vanish(self, ref: str, timeout: float = 300.0) -> None:
        """Ждёт, пока эталон исчезнет с экрана (например, индикатор прогресса)."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if not self.exists(ref, timeout=1.0):
                return
            time.sleep(1.0)
        self.capture("still_visible")
        raise UiError(f"«{ref}» так и не исчез за {timeout:.0f}с (операция не завершилась?).")

    def type_text(self, text: str, interval: float = 0.02) -> None:
        """Ввод текста. Для кириллицы (и любого не-ASCII) pyautogui.typewrite
        не работает — печатает пустоту/мусор. Поэтому такой текст вводим через
        буфер обмена (надёжно для русского «блок» и т.п.)."""
        if text.isascii():
            self.pg.typewrite(text, interval=interval)
            return
        self.paste_text(text)

    def paste_text(self, text: str) -> None:
        """Кладёт текст в буфер обмена и вставляет его (Ctrl+V). Единственный
        надёжный способ ввести кириллицу в CapCut через автоматизацию."""
        if self._set_clipboard(text):
            self.pg.hotkey("ctrl", "v")
            logger.info("Вставлен текст из буфера: %r", text)
            time.sleep(0.2)
            return
        # Крайний случай: пробуем посимвольно (сработает только для ASCII).
        logger.warning("Буфер обмена недоступен — печатаю посимвольно (кириллица может не ввестись).")
        self.pg.typewrite(text, interval=0.03)

    @staticmethod
    def _set_clipboard(text: str) -> bool:
        try:
            import pyperclip  # type: ignore

            pyperclip.copy(text)
            return True
        except Exception:  # noqa: BLE001
            pass
        # Fallback: буфер обмена Windows через ctypes (без внешних пакетов).
        try:
            import ctypes

            CF_UNICODETEXT = 13
            GMEM_MOVEABLE = 0x0002
            user32 = ctypes.windll.user32  # type: ignore[attr-defined]
            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            if not user32.OpenClipboard(0):
                return False
            try:
                user32.EmptyClipboard()
                buf = text + "\x00"
                size = len(buf) * 2
                h = kernel32.GlobalAlloc(GMEM_MOVEABLE, size)
                lock = kernel32.GlobalLock(h)
                ctypes.memmove(lock, ctypes.create_unicode_buffer(buf), size)
                kernel32.GlobalUnlock(h)
                user32.SetClipboardData(CF_UNICODETEXT, h)
            finally:
                user32.CloseClipboard()
            return True
        except Exception:  # noqa: BLE001
            return False

    def hotkey(self, *keys: str) -> None:
        self.pg.hotkey(*keys)
        logger.info("Горячие клавиши: %s", "+".join(keys))

    def press(self, key: str, presses: int = 1) -> None:
        self.pg.press(key, presses=presses)

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)
