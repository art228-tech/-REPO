"""Использованные материалы уносятся в отдельную папку.

Именно уносятся, а не удаляются: если партию придётся пересобрать, исходники
останутся на месте. Сценарий уходит вместе со своей озвучкой — иначе в папке
копятся текстовики без звуковых файлов.
"""
from __future__ import annotations

from pathlib import Path

from capcut_uniq import assets, textalign


def _voices(tmp_path: Path, *names: str) -> Path:
    folder = tmp_path / "озвучки"
    folder.mkdir(parents=True, exist_ok=True)
    for name in names:
        (folder / f"{name}.mp3").write_bytes(b"\x00")
        (folder / f"{name}.txt").write_text("текст", encoding="utf-8")
    return folder


def test_files_are_moved_not_deleted(tmp_path: Path):
    folder = _voices(tmp_path, "0136")
    used = tmp_path / "использовано"

    assets.consume([folder / "0136.mp3"], used)

    assert not (folder / "0136.mp3").exists()
    assert (used / "0136.mp3").exists()


def test_script_travels_with_its_voice(tmp_path: Path):
    folder = _voices(tmp_path, "0136", "0137", "0138")
    used = tmp_path / "использовано"

    voice = folder / "0137.mp3"
    assets.consume([voice, textalign.find_script(voice)], used)

    assert sorted(p.name for p in used.iterdir()) == ["0137.mp3", "0137.txt"]
    # Соседи не тронуты, пары целы.
    assert sorted(p.name for p in folder.iterdir()) == [
        "0136.mp3", "0136.txt", "0138.mp3", "0138.txt",
    ]


def test_same_name_does_not_overwrite(tmp_path: Path):
    folder = _voices(tmp_path, "0136")
    used = tmp_path / "использовано"
    used.mkdir()
    (used / "0136.mp3").write_bytes(b"\x01")

    assets.consume([folder / "0136.mp3"], used)

    assert sorted(p.name for p in used.iterdir()) == ["0136.mp3", "0136_1.mp3"]


def test_missing_file_is_skipped(tmp_path: Path):
    used = tmp_path / "использовано"
    assert assets.consume([tmp_path / "нет.mp3"], used) == []


def test_voice_without_script_is_fine(tmp_path: Path):
    folder = tmp_path / "озвучки"
    folder.mkdir()
    (folder / "0136.mp3").write_bytes(b"\x00")
    used = tmp_path / "использовано"

    voice = folder / "0136.mp3"
    assert textalign.find_script(voice) is None
    assets.consume([voice], used)
    assert (used / "0136.mp3").exists()
