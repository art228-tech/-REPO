"""Тесты нечёткого сопоставления текста кнопок с учётом свода гомоглифов.

OCR часто искажает кириллицу в похожие латинские буквы («Субтитры» → «Cy6TUTpbl»).
Проверяем, что сопоставление всё равно находит нужную кнопку и не срабатывает
на отсутствующей.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.ui_automation.ocr import TextBox, best_match, fold, similarity


def _menu():
    # то, что реально распознал OCR на верхнем меню CapCut (искажённая кириллица)
    return [
        TextBox("MeAnaMaTepNabl", 123, 40, 0.9),
        TextBox("3ByK", 288, 40, 0.9),
        TextBox("TeKCT", 382, 39, 0.9),
        TextBox("CTUKepbl", 500, 40, 0.9),
        TextBox("Cy6TUTpbl", 939, 40, 0.9),
        TextBox("ΦubTpbl", 1082, 40, 0.9),
    ]


def test_fold_nonempty():
    assert fold("Субтитры")
    assert fold("Экспорт")


def test_subtitles_matched_at_right_position():
    m = best_match(["Субтитры", "Субтитр"], _menu(), min_score=0.7)
    assert m is not None
    assert m[0].cx == 939  # правильная позиция «Субтитры»


def test_text_matched():
    m = best_match(["Текст"], _menu(), min_score=0.7)
    assert m is not None and m[0].cx == 382


def test_absent_word_rejected():
    m = best_match(["Экспорт"], _menu(), min_score=0.7)
    assert m is None  # «Экспорт» в этом меню нет — не должно ложно сработать


def test_substring_match():
    boxes = [TextBox("Частотакадров 60fps", 100, 10, 0.9)]
    m = best_match(["60fps"], boxes, min_score=0.7)
    assert m is not None


def test_similarity_bounds():
    assert similarity("Экспорт", "Экспорт") > 0.99
    assert similarity("Экспорт", "Медиаматериалы") < 0.6


if __name__ == "__main__":
    import traceback

    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception:  # noqa: BLE001
            failed += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
