"""Три ролика из одного набора материалов: обычный кадр и два со сдвигом вбок.

Клип шире кадра — при масштабе больше единицы его бока обрезаны, и там остаётся
неиспользованная картинка. Сдвиг её открывает: часть прежнего кадра уходит,
столько же приходит с обрезанной стороны.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from capcut_uniq import builder
from capcut_uniq.batch import FRAME_SHIFT, frame_shifts, widest_slots
from capcut_uniq.config import Config


def _config(**kwargs) -> Config:
    return Config(clips_dir=Path("."), voice_dir=Path("."), **kwargs)


def test_one_frame_by_default():
    assert frame_shifts(_config()) == [0.0]


def test_three_frames_when_asked():
    shifts = frame_shifts(_config(three_frames=True))
    assert len(shifts) == 3
    assert shifts[0] == 0.0
    assert shifts[1] == -FRAME_SHIFT
    assert shifts[2] == FRAME_SHIFT


def test_two_thirds_of_the_frame_stays():
    """Сдвиг на треть ширины: две трети прежнего кадра остаются на месте."""
    assert FRAME_SHIFT == pytest.approx(1 / 3)


def _shift(scale: float, share: float, start: float = 0.0):
    clip = {"transform": {"x": start}}
    notes: list[str] = []
    builder._shift_frame(clip, scale, share, position=0, is_overlay=False, notes=notes)
    return clip["transform"]["x"], notes


def test_shift_is_doubled_for_the_draft():
    """В черновике сдвиг записан в долях половины ширины, а не всей."""
    moved, notes = _shift(scale=3.0, share=1 / 3)
    assert moved == pytest.approx(2 / 3)
    assert not notes


def test_left_and_right_are_mirrored():
    left, _ = _shift(scale=3.0, share=-1 / 3)
    right, _ = _shift(scale=3.0, share=1 / 3)
    assert left == pytest.approx(-right)


def test_shift_adds_to_what_the_template_had():
    moved, _ = _shift(scale=3.0, share=1 / 3, start=0.2)
    assert moved == pytest.approx(0.2 + 2 / 3)


def test_shift_stops_at_the_edge_of_the_clip():
    """За краем клипа пустота, поэтому дальше запаса не двигаем."""
    moved, notes = _shift(scale=1.2, share=1 / 3)
    assert moved == pytest.approx(0.2)
    assert notes and "нет запаса" in notes[0]


def test_clip_that_exactly_fills_the_frame_does_not_move():
    moved, notes = _shift(scale=1.0, share=1 / 3)
    assert moved == 0.0
    assert notes


def test_wide_clip_moves_the_whole_way():
    """У фона масштаб около четырёх — запаса вдоволь."""
    moved, notes = _shift(scale=4.0, share=1 / 3)
    assert moved == pytest.approx(2 / 3)
    assert not notes


def test_overlay_does_not_add_its_own_note():
    """Про урезанный сдвиг достаточно сказать один раз на слот."""
    clip = {"transform": {"x": 0.0}}
    notes: list[str] = []
    builder._shift_frame(clip, 1.1, 1 / 3, position=0, is_overlay=True, notes=notes)
    assert not notes


def test_missing_transform_is_created():
    clip: dict = {}
    builder._shift_frame(clip, 3.0, 1 / 3, position=0, is_overlay=False, notes=[])
    assert clip["transform"]["x"] == pytest.approx(2 / 3)


class _Line:
    def __init__(self, short: int, long: int):
        self.slot_durations = [short, long]


def test_clips_are_chosen_for_the_longest_voice():
    """Клипы у набора общие, а озвучки разной длины — берём под самую длинную."""
    lines = [_Line(2_000_000, 9_000_000),
             _Line(3_500_000, 7_000_000),
             _Line(2_800_000, 12_000_000)]
    assert widest_slots(lines) == [3_500_000, 12_000_000]


def test_single_voice_asks_for_its_own_slots():
    assert widest_slots([_Line(2_000_000, 9_000_000)]) == [2_000_000, 9_000_000]


def test_no_voices_is_an_error():
    from capcut_uniq.errors import PipelineError

    with pytest.raises(PipelineError):
        widest_slots([])
