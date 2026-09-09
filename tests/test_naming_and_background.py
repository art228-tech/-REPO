"""Случайные имена проектов и ролики без размытого фона."""
from __future__ import annotations

import random
from pathlib import Path

import pytest

from capcut_uniq import naming


def test_random_name_has_the_asked_length():
    rng = random.Random(1)
    for length in (4, 8, 10, 24):
        assert len(naming.random_name(rng, length)) == length


def test_random_name_is_too_short_no_more():
    """Короче четырёх символов имя не даём: слишком велик риск совпадений."""
    assert len(naming.random_name(random.Random(1), 1)) == 4


def test_random_name_uses_only_letters_and_digits():
    rng = random.Random(2)
    allowed = set((naming.ALPHABET + naming.ALPHABET.upper()))
    for _ in range(200):
        assert set(naming.random_name(rng, 12)) <= allowed


def test_names_are_varied():
    """Двести имён — и ни одного повтора, иначе смысла в случайности нет."""
    rng = random.Random(3)
    names = {naming.random_name(rng, 10) for _ in range(200)}
    assert len(names) == 200


def test_both_alphabets_and_digits_and_cases_appear():
    rng = random.Random(4)
    everything = "".join(naming.random_name(rng, 10) for _ in range(200))
    assert any(symbol in naming.RUSSIAN for symbol in everything.lower())
    assert any(symbol in naming.ENGLISH for symbol in everything.lower())
    assert any(symbol in naming.DIGITS for symbol in everything)
    assert any(symbol.isupper() for symbol in everything)
    assert any(symbol.islower() for symbol in everything)


def test_taken_names_are_avoided():
    rng = random.Random(5)
    busy = {naming.random_name(random.Random(5), 6) for _ in range(3)}
    for _ in range(50):
        assert naming.random_name(rng, 6, busy) not in busy


def test_taken_names_are_avoided_whatever_the_case():
    """CapCut на Windows не различает регистр в именах папок."""
    rng = random.Random(6)
    name = naming.random_name(random.Random(6), 8)
    for _ in range(30):
        made = naming.random_name(rng, 8, {name.upper(), name.lower()})
        assert made.casefold() != name.casefold()


def test_occupied_lists_only_folders(tmp_path: Path):
    (tmp_path / "проект").mkdir()
    (tmp_path / "ещё").mkdir()
    (tmp_path / "файл.json").write_text("{}", encoding="utf-8")
    assert naming.occupied(tmp_path) == {"проект", "ещё"}
    assert naming.occupied(tmp_path / "нет такой") == set()


def test_no_black_background_by_default():
    assert naming.black_background_numbers(24, 0, random.Random(1)) == set()


def test_share_holds_across_the_batch():
    """Два из шести должно давать восемь из двадцати четырёх."""
    chosen = naming.black_background_numbers(24, 2, random.Random(1))
    assert len(chosen) == 8
    for start in (1, 7, 13, 19):
        group = set(range(start, start + 6))
        assert len(chosen & group) == 2


def test_places_differ_from_run_to_run():
    first = naming.black_background_numbers(24, 2, random.Random(1))
    second = naming.black_background_numbers(24, 2, random.Random(9))
    assert first != second


def test_every_video_can_be_without_background():
    assert naming.black_background_numbers(6, 6, random.Random(1)) == set(range(1, 7))


def test_short_batch_keeps_a_sensible_share():
    """В партии из трёх при доле два из шести хватает одного ролика."""
    chosen = naming.black_background_numbers(3, 2, random.Random(1))
    assert len(chosen) == 1
    assert chosen <= {1, 2, 3}


def test_share_is_clamped_to_the_group():
    chosen = naming.black_background_numbers(4, 99, random.Random(1))
    assert chosen == {1, 2, 3, 4}


@pytest.mark.parametrize("count", [1, 5, 6, 7, 13, 24, 30])
def test_numbers_stay_inside_the_batch(count: int):
    chosen = naming.black_background_numbers(count, 3, random.Random(count))
    assert chosen <= set(range(1, count + 1))
