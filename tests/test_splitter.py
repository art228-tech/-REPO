"""Нарезка видео: разбор схемы длин и расчёт кусков."""
from __future__ import annotations

import pytest

from capcut_uniq.errors import PipelineError
from capcut_uniq.splitter import parse_pattern, plan_cuts


def test_pattern_formats():
    assert parse_pattern("4") == [4.0]
    assert parse_pattern("4 15") == [4.0, 15.0]
    assert parse_pattern("4, 15") == [4.0, 15.0]
    assert parse_pattern("2.5;7") == [2.5, 7.0]


def test_pattern_rejects_nonsense():
    with pytest.raises(PipelineError):
        parse_pattern("")
    with pytest.raises(PipelineError):
        parse_pattern("четыре")
    with pytest.raises(PipelineError):
        parse_pattern("0")


def test_equal_pieces():
    pieces, tail = plan_cuts(duration_s=20.0, pattern=[4.0])
    assert len(pieces) == 5
    assert [piece.start_s for piece in pieces] == [0.0, 4.0, 8.0, 12.0, 16.0]
    assert all(piece.duration_s == 4.0 for piece in pieces)
    assert tail == 0.0


def test_alternating_pattern():
    """Схема «4 15» даёт 4, 15, 4, 15 и так до конца."""
    pieces, _ = plan_cuts(duration_s=38.0, pattern=[4.0, 15.0])
    assert [piece.duration_s for piece in pieces] == [4.0, 15.0, 4.0, 15.0]
    assert [piece.start_s for piece in pieces] == [0.0, 4.0, 19.0, 23.0]


def test_trims_applied():
    pieces, _ = plan_cuts(duration_s=30.0, pattern=[5.0], trim_start_s=3.0, trim_end_s=2.0)
    assert pieces[0].start_s == 3.0
    assert len(pieces) == 5
    assert pieces[-1].start_s + pieces[-1].duration_s == 28.0


def test_incomplete_tail_dropped_by_default():
    pieces, tail = plan_cuts(duration_s=10.0, pattern=[4.0])
    assert [piece.duration_s for piece in pieces] == [4.0, 4.0]
    assert tail == pytest.approx(2.0)


def test_incomplete_tail_can_be_kept():
    pieces, tail = plan_cuts(duration_s=10.0, pattern=[4.0], keep_tail=True)
    assert [piece.duration_s for piece in pieces] == [4.0, 4.0, 2.0]
    assert tail == 0.0
    assert pieces[-1].is_short


def test_trim_leaves_nothing():
    with pytest.raises(PipelineError) as info:
        plan_cuts(duration_s=10.0, pattern=[4.0], trim_start_s=6.0, trim_end_s=5.0)
    assert "не остаётся материала" in str(info.value)


def test_long_pattern_element_yields_nothing():
    """Если первый же кусок не влезает, список пуст, а весь остаток в хвосте."""
    pieces, tail = plan_cuts(duration_s=3.0, pattern=[10.0])
    assert pieces == []
    assert tail == pytest.approx(3.0)
