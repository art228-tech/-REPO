"""Поиск элементов интерфейса по ТЕКСТУ (OCR) — надёжная замена поиску по
картинкам-эталонам.

Почему так надёжнее: кнопки CapCut подписаны текстом («Субтитры», «Экспорт»,
«Создать», «Основн.», «Шаблоны», «1080P», «60fps», «Выше», имена шрифтов
«Блок-hv» и т.д.). Их положение находится по подписи независимо от разрешения
экрана, темы, масштаба и сглаживания — то, на чём ломался поиск по PNG-эталонам.

Распознавание — rapidocr-onnxruntime (офлайн, ставится через pip, без внешних
бинарников). Кириллицу OCR часто путает с похожими латинскими буквами
(«Субтитры» → «Cy6TUTpbl»), поэтому сравнение идёт с «сводом гомоглифов»
(похожие кириллица/латиница приводятся к общему виду) и нечётко (difflib).
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher

from ..logging_setup import get_logger

logger = get_logger()

# Свод похожих по начертанию кириллических и латинских букв к общему виду.
# Это позволяет сопоставлять «Субтитры» с распознанным «Cy6TUTpbl».
_FOLD_MAP = {
    "а": "a", "е": "e", "о": "o", "с": "c", "р": "p", "у": "y", "х": "x",
    "к": "k", "м": "m", "т": "t", "н": "h", "в": "b", "и": "u", "б": "6",
    "л": "l", "ы": "bl", "з": "3", "ф": "q", "д": "a", "п": "n", "г": "r",
}
_FOLD = str.maketrans({**_FOLD_MAP, **{k.upper(): v for k, v in _FOLD_MAP.items()}})


def fold(s: str) -> str:
    """Приводит строку к каноническому виду для нечёткого сравнения."""
    s = (s or "").lower().translate(_FOLD)
    return "".join(ch for ch in s if ch.isalnum())


def similarity(a: str, b: str) -> float:
    """Похожесть двух строк 0..1 с учётом свода гомоглифов.
    Учитывает и полное совпадение, и вхождение подстрокой (короткая подпись
    внутри длинного распознанного блока)."""
    fa, fb = fold(a), fold(b)
    if not fa or not fb:
        return 0.0
    ratio = SequenceMatcher(None, fa, fb).ratio()
    # Вхождение (например, «60fps» внутри «частотакадров60fps»).
    short, long = (fa, fb) if len(fa) <= len(fb) else (fb, fa)
    if short and short in long:
        ratio = max(ratio, 0.9 + 0.1 * len(short) / len(long))
    return ratio


@dataclass
class TextBox:
    text: str
    cx: float
    cy: float
    conf: float


class OcrEngine:
    """Ленивая обёртка над RapidOCR (грузится один раз при первом вызове)."""

    def __init__(self) -> None:
        self._ocr = None
        self._unavailable = False

    def available(self) -> bool:
        if self._unavailable:
            return False
        if self._ocr is not None:
            return True
        try:
            from rapidocr_onnxruntime import RapidOCR  # type: ignore

            self._ocr = RapidOCR()
            return True
        except Exception as e:  # noqa: BLE001
            logger.warning("OCR недоступен (rapidocr не загрузился): %s", e)
            self._unavailable = True
            return False

    def read(self, image) -> list[TextBox]:
        """Распознаёт текст на изображении (PIL.Image или путь/np.array).
        Возвращает список блоков с центрами."""
        if not self.available():
            return []
        try:
            import numpy as np  # type: ignore

            arr = image
            if hasattr(image, "convert"):  # PIL.Image
                arr = np.array(image.convert("RGB"))
            result, _ = self._ocr(arr)
        except Exception as e:  # noqa: BLE001
            logger.warning("Ошибка OCR: %s", e)
            return []
        boxes: list[TextBox] = []
        for item in result or []:
            try:
                quad, text, conf = item
                cx = sum(p[0] for p in quad) / 4.0
                cy = sum(p[1] for p in quad) / 4.0
                boxes.append(TextBox(str(text), float(cx), float(cy), float(conf)))
            except Exception:  # noqa: BLE001
                continue
        return boxes


def best_match(targets: list[str], boxes: list[TextBox],
               min_score: float = 0.7) -> tuple[TextBox, float] | None:
    """Находит блок текста, лучше всего совпадающий с одним из `targets`.
    Возвращает (блок, score) или None, если ничего не прошло порог."""
    best: tuple[TextBox, float] | None = None
    for box in boxes:
        for t in targets:
            sc = similarity(t, box.text)
            if best is None or sc > best[1]:
                best = (box, sc)
    if best is not None and best[1] >= min_score:
        return best
    return None
