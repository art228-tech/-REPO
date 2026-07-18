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

logger = get_logger()


class UiError(Exception):
    """Ошибка UI-автоматизации (не нашли элемент, таймаут и т.п.)."""


class Screen:
    def __init__(self, references_dir: Path, shots_dir: Path,
                 confidence: float = 0.85, default_timeout: float = 30.0) -> None:
        self.references_dir = Path(references_dir)
        self.shots_dir = Path(shots_dir)
        self.confidence = confidence
        self.default_timeout = default_timeout
        self._pg = None

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
        p = self.references_dir / ref
        if not p.suffix:
            p = p.with_suffix(".png")
        return p

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
        last_err: Exception | None = None
        while time.time() < deadline:
            try:
                loc = self.pg.locateCenterOnScreen(str(ref_path), confidence=conf)
                if loc is not None:
                    return loc
            except Exception as e:  # noqa: BLE001 — pyautogui бросает при отсутствии
                last_err = e
            time.sleep(0.5)
        self.capture(f"not_found_{ref_path.stem}")
        raise UiError(
            f"Не нашёл на экране «{ref_path.name}» за {timeout:.0f}с. "
            f"Скриншот экрана сохранён в logs/screenshots. "
            f"Проверьте, что кнопка видна и скриншот-эталон актуален."
            + (f" ({last_err})" if last_err else "")
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
              confidence: float | None = None, clicks: int = 1) -> None:
        x, y = self.locate(ref, timeout=timeout, confidence=confidence)
        self.pg.click(x, y, clicks=clicks)
        logger.info("Клик по «%s» в (%d, %d)%s", ref, x, y,
                    " x2" if clicks == 2 else "")

    def double_click(self, ref: str, **kw) -> None:
        self.click(ref, clicks=2, **kw)

    def click_xy(self, x: int, y: int) -> None:
        self.pg.click(x, y)

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
        self.pg.typewrite(text, interval=interval)

    def hotkey(self, *keys: str) -> None:
        self.pg.hotkey(*keys)
        logger.info("Горячие клавиши: %s", "+".join(keys))

    def press(self, key: str, presses: int = 1) -> None:
        self.pg.press(key, presses=presses)

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)
