"""Повторная нарезка того же видео не должна затирать прежние клипы.

Имя клипа складывается из имени исходника и номера, а номер раньше начинался
с единицы в каждом прогоне. Из-за этого восемнадцать нарезок двух видео оставили
в папке материал только двух последних прогонов.
"""
from __future__ import annotations

from pathlib import Path

from capcut_uniq.splitter import _last_index


def _make(folder: Path, *names: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    for name in names:
        (folder / name).write_bytes(b"\x00")
    return folder


def test_empty_folder_starts_from_scratch(tmp_path: Path):
    assert _last_index("видео", ".mp4", {tmp_path}) == 0


def test_highest_number_is_found(tmp_path: Path):
    folder = _make(tmp_path / "клипы",
                   "видео_001_15s.mp4", "видео_022_15s.mp4", "видео_007_15s.mp4")
    assert _last_index("видео", ".mp4", {folder}) == 22


def test_numbers_are_counted_across_all_folders(tmp_path: Path):
    short = _make(tmp_path / "кор", "видео_003_4s.mp4")
    long = _make(tmp_path / "длин", "видео_014_15s.mp4")
    assert _last_index("видео", ".mp4", {short, long}) == 14


def test_other_sources_do_not_count(tmp_path: Path):
    folder = _make(tmp_path / "клипы", "другое_099_15s.mp4", "видео_004_15s.mp4")
    assert _last_index("видео", ".mp4", {folder}) == 4


def test_foreign_names_are_ignored(tmp_path: Path):
    folder = _make(tmp_path / "клипы",
                   "видео_005_15s.mp4", "видео.mp4", "видео_готово.mp4",
                   "заметка.txt", "видео_007_15s.txt")
    assert _last_index("видео", ".mp4", {folder}) == 5


def test_missing_folder_is_not_a_problem(tmp_path: Path):
    assert _last_index("видео", ".mp4", {tmp_path / "нет такой"}) == 0


def test_name_with_dots_and_underscores(tmp_path: Path):
    """Имена исходников бывают вида lv_0_20260814134630."""
    folder = _make(tmp_path / "клипы",
                   "lv_0_20260814134630_022_15s.mp4",
                   "lv_0_20260814131032_007_15s.mp4")
    assert _last_index("lv_0_20260814134630", ".mp4", {folder}) == 22
    assert _last_index("lv_0_20260814131032", ".mp4", {folder}) == 7


def test_fractional_length_in_the_name(tmp_path: Path):
    folder = _make(tmp_path / "клипы", "видео_012_4.5s.mp4")
    assert _last_index("видео", ".mp4", {folder}) == 12
