"""Раскладка нарезанных клипов по папкам."""
from __future__ import annotations

from pathlib import Path

import pytest

from capcut_uniq.errors import PipelineError
from capcut_uniq.splitter import key, pattern_lengths, resolve_targets


def test_distinct_lengths_in_order_of_appearance():
    assert pattern_lengths([4.0, 15.0, 4.0, 15.0]) == [4.0, 15.0]
    assert pattern_lengths([15.0, 4.0]) == [15.0, 4.0]
    assert pattern_lengths([4.0]) == [4.0]


def test_single_folder_takes_everything():
    targets = resolve_targets([4.0, 15.0], Path("D:/клипы"))
    assert targets == {4.0: Path("D:/клипы"), 15.0: Path("D:/клипы")}


def test_folders_matched_to_lengths_in_order():
    """При схеме «4 15» первая папка достаётся коротким, вторая длинным."""
    targets = resolve_targets([4.0, 15.0], [Path("D:/short"), Path("D:/long")])
    assert targets[key(4.0)] == Path("D:/short")
    assert targets[key(15.0)] == Path("D:/long")


def test_reversed_pattern_reverses_mapping():
    targets = resolve_targets([15.0, 4.0], [Path("D:/long"), Path("D:/short")])
    assert targets[key(15.0)] == Path("D:/long")
    assert targets[key(4.0)] == Path("D:/short")


def test_count_mismatch_explains_itself():
    with pytest.raises(PipelineError) as info:
        resolve_targets([4.0, 15.0], [Path("a"), Path("b"), Path("c")])
    assert "2 разных длин" in str(info.value)


def test_mapping_accepted_directly():
    targets = resolve_targets([4.0, 15.0], {4.0: Path("a"), 15.0: Path("b")})
    assert targets == {4.0: Path("a"), 15.0: Path("b")}


def test_mapping_must_cover_every_length():
    with pytest.raises(PipelineError) as info:
        resolve_targets([4.0, 15.0], {4.0: Path("a")})
    assert "15с" in str(info.value)


def test_no_folder_at_all():
    with pytest.raises(PipelineError):
        resolve_targets([4.0], [])


def test_config_accepts_one_or_many_clip_folders():
    from capcut_uniq.config import Config

    one = Config(clips_dir=Path("D:/клипы"), voice_dir=Path("D:/озвучки"))
    assert one.clip_folders == [Path("D:/клипы")]

    many = Config(clips_dir=[Path("D:/short"), Path("D:/long")], voice_dir=Path("D:/озвучки"))
    assert many.clip_folders == [Path("D:/short"), Path("D:/long")]
