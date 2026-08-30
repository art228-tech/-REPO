"""Клип чуть короче слота и пропуск неудачной озвучки.

Нарезка на куски по 15с даёт файлы ровно 15.00с, а слот под озвучку запросто
выходит 15.15с. Раньше из-за таких 0.15с вылетала озвучка, а вместе с ней вставала
вся партия — вместо двадцати четырёх роликов получалось четыре.
"""
from __future__ import annotations

import pytest

from capcut_uniq import assets
from capcut_uniq.errors import AssetShortage


class _Clip:
    def __init__(self, name: str, duration: float):
        self.path = name
        self.duration_s = duration

    def __repr__(self) -> str:
        return f"<{self.path} {self.duration_s}>"


def _pool(*durations: float) -> assets.Pool:
    pool = assets.Pool.__new__(assets.Pool)
    pool.items = [_Clip(f"c{i}.mp4", d) for i, d in enumerate(durations)]
    pool.folders = []
    pool.kind = "клипы"
    return pool


def test_slightly_short_clip_is_accepted_with_stretch():
    """Клип 15.00с должен подойти под слот 15.15с."""
    pool = _pool(4.0, 15.0)
    chosen = pool.take_longest_enough(15.155, stretch=0.06)
    assert chosen.duration_s == 15.0


def test_short_clip_is_refused_without_stretch():
    pool = _pool(4.0, 15.0)
    with pytest.raises(AssetShortage):
        pool.take_longest_enough(15.155)


def test_too_short_clip_is_refused_even_with_stretch():
    """Замедление закрывает малую нехватку, а не любую."""
    pool = _pool(4.0, 15.0)
    with pytest.raises(AssetShortage):
        pool.take_longest_enough(25.0, stretch=0.06)


def test_shortest_sufficient_clip_is_taken_first():
    """Длинные клипы надо беречь для длинных слотов."""
    pool = _pool(4.0, 8.0, 15.0, 20.0)
    assert pool.take_longest_enough(7.0).duration_s == 8.0
    assert pool.take_longest_enough(14.0).duration_s == 15.0


def test_message_names_the_longest_left():
    pool = _pool(3.0, 9.5)
    with pytest.raises(AssetShortage) as caught:
        pool.take_longest_enough(20.0)
    assert "9.50" in str(caught.value)


def test_taken_clip_can_be_given_back():
    """Набор не сложился — клип должен вернуться в пул, а не пропасть."""
    pool = _pool(4.0, 15.0)
    taken = pool.take_longest_enough(14.0)
    assert len(pool.items) == 1

    pool.give_back(taken)
    assert len(pool.items) == 2
    assert pool.take_longest_enough(14.0) is taken


def test_giving_back_twice_does_not_double():
    pool = _pool(15.0)
    taken = pool.take_longest_enough(14.0)
    pool.give_back(taken)
    pool.give_back(taken)
    assert len(pool.items) == 1


def test_pair_is_returned_when_the_second_clip_is_missing():
    """Первый клип уже взят, второго нет — оба должны остаться в пуле."""
    from capcut_uniq.batch import _take_clips

    pool = _pool(4.0, 9.0)
    with pytest.raises(AssetShortage):
        _take_clips(pool, [3_000_000, 20_000_000], 0.0)
    assert len(pool.items) == 2


def test_pair_is_taken_when_both_fit():
    from capcut_uniq.batch import _take_clips

    pool = _pool(4.0, 9.0, 20.0)
    taken = _take_clips(pool, [3_000_000, 19_000_000], 0.0)
    assert [item.duration_s for item in taken] == [4.0, 20.0]
    assert len(pool.items) == 1


def test_stretch_lowers_the_bar_by_the_right_amount():
    """Порог должен быть длиной слота, поделённой на запас."""
    pool = _pool(14.30)
    # 15.15 / 1.06 = 14.29 — клип 14.30 проходит
    assert pool.take_longest_enough(15.155, stretch=0.06).duration_s == 14.30

    pool = _pool(14.20)
    with pytest.raises(AssetShortage):
        pool.take_longest_enough(15.155, stretch=0.06)
