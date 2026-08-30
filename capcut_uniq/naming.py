"""Имена проектов.

Обычное имя — «префикс_дата_номер», по нему видно, когда и чем собрано. Но такое
имя выдаёт, что ролики сделаны пачкой одним инструментом, поэтому есть и второй
вид: случайный набор русских и английских букв и цифр со смешанным регистром.
"""
from __future__ import annotations

import random
from pathlib import Path

from .logging_setup import get_logger

log = get_logger("naming")

RUSSIAN = "абвгдежзийклмнопрстуфхцчшщэюя"
ENGLISH = "abcdefghijklmnopqrstuvwxyz"
DIGITS = "0123456789"

# Ё и Й в именах папок читаются плохо, а «ы», «ъ», «ь» не бывают заглавными в
# начале слова — но внутри случайного набора это неважно, поэтому берём алфавит
# целиком, кроме ё.
ALPHABET = RUSSIAN + ENGLISH + DIGITS


def random_name(rng: random.Random, length: int = 10, taken: set[str] | None = None) -> str:
    """Случайное имя из русских и английских букв и цифр, регистр вперемешку."""
    length = max(4, int(length))
    taken = taken or set()

    for _ in range(200):
        letters = []
        for _ in range(length):
            symbol = rng.choice(ALPHABET)
            letters.append(symbol.upper() if rng.random() < 0.5 else symbol)
        name = "".join(letters)
        # Имя из одних цифр выглядит как номер, а не как название.
        if name.isdigit():
            continue
        if name.casefold() not in {item.casefold() for item in taken}:
            return name

    raise RuntimeError("не удалось придумать свободное имя")


def occupied(folder: Path) -> set[str]:
    """Имена, которые уже заняты папками проектов."""
    root = Path(folder)
    if not root.is_dir():
        return set()
    return {item.name for item in root.iterdir() if item.is_dir()}


def black_background_numbers(count: int, per_six: int, rng: random.Random) -> set[int]:
    """Номера роликов, которые собираются без размытого фона.

    Доля задана «столько-то из шести», поэтому партия делится на шестёрки и в
    каждой случайно выбираются номера. При такой раскладке доля держится и на
    шести роликах, и на двадцати четырёх, а места каждый раз разные.
    """
    per_six = max(0, min(6, int(per_six)))
    if per_six == 0 or count <= 0:
        return set()

    chosen: set[int] = set()
    for start in range(1, count + 1, 6):
        group = list(range(start, min(start + 6, count + 1)))
        # В неполной шестёрке берём долю от её размера, чтобы хвост не перекосило.
        share = max(1, round(per_six * len(group) / 6)) if len(group) < 6 else per_six
        chosen.update(rng.sample(group, min(share, len(group))))

    log.debug("без размытого фона: %s", ", ".join(str(n) for n in sorted(chosen)))
    return chosen
