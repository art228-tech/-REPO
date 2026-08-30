"""Единицы времени.

CapCut хранит все тайминги в микросекундах, а внутри текстовых материалов
(массив ``words``) — в миллисекундах относительно начала субтитра.
"""
from __future__ import annotations

US = 1_000_000
MS = 1_000


def s2us(seconds: float) -> int:
    return int(round(seconds * US))


def us2s(microseconds: int | float) -> float:
    return float(microseconds) / US


def s2ms(seconds: float) -> int:
    return int(round(seconds * MS))


def fmt(microseconds: int | float) -> str:
    """Человекочитаемое время для логов: 12.853с."""
    return f"{us2s(microseconds):.3f}с"
