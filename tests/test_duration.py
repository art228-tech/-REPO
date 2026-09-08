import pytest

from elevenlabs_voiceover import duration
from elevenlabs_voiceover.config import describe_duration_limits
from elevenlabs_voiceover.errors import Cancelled

#: Целый кадр MPEG1 Layer III: 128 кбит/с, 44100 Гц, 1152 отсчёта.
FRAME = b"\xff\xfb\x90\x00" + b"\x00" * 413
FRAME_SECONDS = 1152 / 44100


def mp3_lasting(seconds: float) -> bytes:
    return FRAME * max(1, round(seconds / FRAME_SECONDS))


def write_mp3(folder, name: str, seconds: float):
    path = folder / name
    path.write_bytes(mp3_lasting(seconds))
    return path


# ======================================================================
# Границы
# ======================================================================
def test_names_the_broken_limit():
    assert duration.duration_problem(4.0, 10, 16) == "короче 10 с"
    assert duration.duration_problem(21.0, 10, 16) == "длиннее 16 с"
    assert duration.duration_problem(12.0, 10, 16) == ""


def test_borders_are_included():
    """Ровно 10 и ровно 16 секунд входят в «от 10 до 16»."""
    assert duration.duration_problem(10.0, 10, 16) == ""
    assert duration.duration_problem(16.0, 10, 16) == ""
    assert duration.duration_problem(9.99, 10, 16) == "короче 10 с"
    assert duration.duration_problem(16.01, 10, 16) == "длиннее 16 с"


def test_zero_switches_the_limit_off():
    assert duration.duration_problem(2.0, 0, 16) == ""
    assert duration.duration_problem(500.0, 10, 0) == ""
    assert duration.duration_problem(500.0, 0, 0) == ""


def test_unmeasured_duration_is_not_a_problem():
    """О файле, длительность которого измерить не вышло, ничего не известно."""
    assert duration.duration_problem(None, 10, 16) == ""


def test_limits_are_described_in_words():
    assert describe_duration_limits(10, 16) == "от 10 до 16 с"
    assert describe_duration_limits(10, 0) == "не короче 10 с"
    assert describe_duration_limits(0, 16) == "не длиннее 16 с"
    assert describe_duration_limits(0, 0) == ""


# ======================================================================
# Что попадает в отбор
# ======================================================================
def test_takes_only_audio_next_to_itself(tmp_path):
    write_mp3(tmp_path, "готово.mp3", 12)
    (tmp_path / "текст.txt").write_text("не звук", encoding="utf-8")
    (tmp_path / "чужое.wav").write_bytes(b"RIFF")

    assert [p.name for p in duration.audio_files(tmp_path)] == ["готово.mp3"]


def test_service_folders_are_left_alone(tmp_path):
    """В `_chunks` лежат куски, в `_voices` — превью: это не готовые озвучки."""
    write_mp3(tmp_path, "готово.mp3", 12)
    for service in ("_chunks", "_voices"):
        (tmp_path / service).mkdir()
        write_mp3(tmp_path / service, "внутри.mp3", 2)
    write_mp3(tmp_path, "_manifest.mp3", 2)

    assert [p.name for p in duration.audio_files(tmp_path)] == ["готово.mp3"]


def test_missing_folder_gives_nothing(tmp_path):
    assert duration.audio_files(tmp_path / "нет") == []


# ======================================================================
# Разбор папки
# ======================================================================
def test_splits_folder_into_three_heaps(tmp_path):
    write_mp3(tmp_path, "короткая.mp3", 4)
    write_mp3(tmp_path, "нормальная.mp3", 12)
    write_mp3(tmp_path, "длинная.mp3", 25)
    (tmp_path / "пустая.mp3").write_bytes(b"\x00" * 100)

    scan = duration.scan_folder(tmp_path, 10, 16)

    assert [item.path.name for item in scan.fitting] == ["нормальная.mp3"]
    assert sorted(item.path.name for item in scan.rejected) == ["длинная.mp3", "короткая.mp3"]
    assert [item.path.name for item in scan.unmeasured] == ["пустая.mp3"]
    assert scan.checked == 4
    assert (scan.too_short, scan.too_long) == (1, 1)


def test_only_the_lower_limit(tmp_path):
    write_mp3(tmp_path, "короткая.mp3", 4)
    write_mp3(tmp_path, "длинная.mp3", 40)

    scan = duration.scan_folder(tmp_path, 10, 0)

    assert [item.path.name for item in scan.rejected] == ["короткая.mp3"]
    assert [item.path.name for item in scan.fitting] == ["длинная.mp3"]


def test_only_the_upper_limit(tmp_path):
    write_mp3(tmp_path, "короткая.mp3", 4)
    write_mp3(tmp_path, "длинная.mp3", 40)

    scan = duration.scan_folder(tmp_path, 0, 16)

    assert [item.path.name for item in scan.rejected] == ["длинная.mp3"]
    assert [item.path.name for item in scan.fitting] == ["короткая.mp3"]


def test_without_limits_nothing_is_rejected(tmp_path):
    write_mp3(tmp_path, "короткая.mp3", 1)
    write_mp3(tmp_path, "длинная.mp3", 300)

    scan = duration.scan_folder(tmp_path, 0, 0)

    assert scan.rejected == []
    assert len(scan.fitting) == 2


def test_scan_touches_nothing_on_disk(tmp_path):
    """Разбор только измеряет: удаление — отдельный шаг, с отдельным согласием."""
    write_mp3(tmp_path, "длинная.mp3", 25)

    duration.scan_folder(tmp_path, 10, 16)

    assert (tmp_path / "длинная.mp3").exists()


def test_scan_reports_progress(tmp_path):
    for i in range(3):
        write_mp3(tmp_path, f"файл{i}.mp3", 12)

    seen = []
    duration.scan_folder(tmp_path, 10, 16, on_progress=lambda done, total, name: seen.append((done, total)))

    assert seen == [(1, 3), (2, 3), (3, 3)]


def test_scan_stops_when_asked(tmp_path):
    import threading

    for i in range(3):
        write_mp3(tmp_path, f"файл{i}.mp3", 12)

    cancel = threading.Event()
    cancel.set()

    with pytest.raises(Cancelled):
        duration.scan_folder(tmp_path, 10, 16, cancel=cancel)


# ======================================================================
# Удаление
# ======================================================================
def test_deletes_only_what_was_given(tmp_path):
    write_mp3(tmp_path, "короткая.mp3", 4)
    write_mp3(tmp_path, "нормальная.mp3", 12)

    scan = duration.scan_folder(tmp_path, 10, 16)
    deleted, errors = duration.delete(scan.rejected)

    assert (deleted, errors) == (1, [])
    assert not (tmp_path / "короткая.mp3").exists()
    assert (tmp_path / "нормальная.mp3").exists()


def test_missing_file_is_reported_not_raised(tmp_path):
    write_mp3(tmp_path, "короткая.mp3", 4)
    scan = duration.scan_folder(tmp_path, 10, 16)
    (tmp_path / "короткая.mp3").unlink()

    deleted, errors = duration.delete(scan.rejected)

    assert deleted == 0
    assert len(errors) == 1
    assert "короткая.mp3" in errors[0]


def test_line_explains_what_is_wrong(tmp_path):
    write_mp3(tmp_path, "длинная.mp3", 25)
    scan = duration.scan_folder(tmp_path, 10, 16)

    assert "длиннее 16 с" in scan.rejected[0].line()
    assert "длинная.mp3" in scan.rejected[0].line()
