"""Отбор готовой папки по длительности из командной строки."""

import pytest

from elevenlabs_voiceover import cli
from elevenlabs_voiceover.config import Settings

FRAME = b"\xff\xfb\x90\x00" + b"\x00" * 413
FRAME_SECONDS = 1152 / 44100


def write_mp3(folder, name: str, seconds: float):
    path = folder / name
    path.write_bytes(FRAME * max(1, round(seconds / FRAME_SECONDS)))
    return path


@pytest.fixture
def folder(tmp_path):
    ready = tmp_path / "готово"
    ready.mkdir()
    write_mp3(ready, "короткая.mp3", 4)
    write_mp3(ready, "нормальная.mp3", 12)
    write_mp3(ready, "длинная.mp3", 25)
    return ready


def names(folder):
    return sorted(p.name for p in folder.iterdir())


def test_deletes_files_outside_the_limits(folder):
    code = cli.main(["--filter", str(folder), "--min-duration", "10", "--max-duration", "16"])

    assert code == 0
    assert names(folder) == ["нормальная.mp3"]


def test_dry_run_touches_nothing(folder):
    code = cli.main([
        "--filter", str(folder), "--min-duration", "10", "--max-duration", "16", "--dry-run",
    ])

    assert code == 0
    assert names(folder) == ["длинная.mp3", "короткая.mp3", "нормальная.mp3"]


def test_lower_limit_alone(folder):
    cli.main(["--filter", str(folder), "--min-duration", "10", "--max-duration", "0"])

    assert names(folder) == ["длинная.mp3", "нормальная.mp3"]


def test_upper_limit_alone(folder):
    cli.main(["--filter", str(folder), "--min-duration", "0", "--max-duration", "16"])

    assert names(folder) == ["короткая.mp3", "нормальная.mp3"]


def test_without_limits_refuses_to_work(folder):
    """Обе границы нулевые — удалять было бы нечего и незачем."""
    code = cli.main(["--filter", str(folder), "--min-duration", "0", "--max-duration", "0"])

    assert code == 2
    assert len(names(folder)) == 3


def test_missing_folder_is_an_error(tmp_path):
    assert cli.main(["--filter", str(tmp_path / "нет"), "--min-duration", "10"]) == 2


def test_service_folders_survive(folder):
    """Превью голосов и куски — тоже mp3, но их отбор не касается."""
    for service in ("_voices", "_chunks"):
        (folder / service).mkdir()
        write_mp3(folder / service, "внутри.mp3", 2)

    cli.main(["--filter", str(folder), "--min-duration", "10", "--max-duration", "16"])

    assert (folder / "_voices" / "внутри.mp3").exists()
    assert (folder / "_chunks" / "внутри.mp3").exists()


def test_limits_come_from_saved_settings(folder):
    """Границы можно один раз сохранить и потом просто вызывать --filter."""
    Settings(min_duration=10.0, max_duration=16.0).save()

    cli.main(["--filter", str(folder)])

    assert names(folder) == ["нормальная.mp3"]


def test_empty_folder_is_not_a_failure(tmp_path):
    empty = tmp_path / "пусто"
    empty.mkdir()

    assert cli.main(["--filter", str(empty), "--min-duration", "10"]) == 0
