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
    """Ленивая обёртка над RapidOCR (грузится один раз при первом вызове).

    Поддерживает оба пакета:
      * `rapidocr` (3.x) — совместим с Python 3.13, новый API (res.boxes/txts);
      * `rapidocr_onnxruntime` (1.x) — старый API (список кортежей).
    Если ни один не установлен — OCR просто недоступен, работает запасной поиск
    по картинкам-эталонам (софт при этом всё равно запускается)."""

    def __init__(self) -> None:
        self._ocr = None
        self._kind = ""  # "new" | "old"
        self._unavailable = False

    def available(self) -> bool:
        if self._unavailable:
            return False
        if self._ocr is not None:
            return True
        # 1) Новый пакет rapidocr (>=3.0), поддерживает Python 3.13.
        try:
            from rapidocr import RapidOCR  # type: ignore

            self._ocr = self._make_new(RapidOCR)
            self._kind = "new"
            logger.info("OCR готов: rapidocr (3.x).")
            return True
        except Exception as e:  # noqa: BLE001
            logger.info("rapidocr (3.x) недоступен: %s", e)
        # 2) Старый пакет rapidocr-onnxruntime (1.x).
        try:
            from rapidocr_onnxruntime import RapidOCR as RapidOCROld  # type: ignore

            self._ocr = RapidOCROld()
            self._kind = "old"
            logger.info("OCR готов: rapidocr-onnxruntime (1.x).")
            return True
        except Exception as e:  # noqa: BLE001
            logger.warning("OCR недоступен (rapidocr не загрузился): %s. "
                           "Будет запасной поиск по картинкам-эталонам.", e)
            self._unavailable = True
            return False

    @staticmethod
    def _make_new(RapidOCR):
        """Создаёт rapidocr 3.x с более точной моделью PP-OCRv4 mobile и
        пониженным порогом детекции (маленькая модель по умолчанию пропускает
        часть подписей). При ошибке — параметры по умолчанию."""
        try:
            from rapidocr import ModelType, OCRVersion  # type: ignore

            params = {
                "Det.ocr_version": OCRVersion.PPOCRV4,
                "Det.model_type": ModelType.MOBILE,
                "Rec.ocr_version": OCRVersion.PPOCRV4,
                "Rec.model_type": ModelType.MOBILE,
                "Det.box_thresh": 0.3,
            }
            return RapidOCR(params=params)
        except Exception as e:  # noqa: BLE001
            logger.info("rapidocr: параметры по умолчанию (%s).", e)
            return RapidOCR()

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
            result = self._ocr(arr)
        except Exception as e:  # noqa: BLE001
            logger.warning("Ошибка OCR: %s", e)
            return []
        return self._parse(result)

    def _parse(self, result) -> list[TextBox]:
        boxes: list[TextBox] = []
        # Новый API: объект с .boxes/.txts/.scores.
        if hasattr(result, "boxes") and hasattr(result, "txts"):
            quads = result.boxes if result.boxes is not None else []
            txts = result.txts or []
            scores = result.scores or []
            for i, quad in enumerate(quads):
                try:
                    cx = sum(float(p[0]) for p in quad) / 4.0
                    cy = sum(float(p[1]) for p in quad) / 4.0
                    txt = str(txts[i]) if i < len(txts) else ""
                    sc = float(scores[i]) if i < len(scores) else 0.0
                    boxes.append(TextBox(txt, cx, cy, sc))
                except Exception:  # noqa: BLE001
                    continue
            return boxes
        # Старый API: (list_of_[quad, text, score], elapse) или просто список.
        items = result
        if isinstance(result, tuple) and result and isinstance(result[0], list):
            items = result[0]
        for item in items or []:
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
