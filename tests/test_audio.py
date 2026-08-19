import shutil
import subprocess

import pytest

from elevenlabs_voiceover.audio import (
    concat_audio,
    extension_for,
    format_family,
    safe_filename,
    strip_id3,
    strip_xing_header,
)

MP3_FRAME = b"\xff\xfb\x90\x00" + b"\x00" * 100

# MPEG1 Layer III, 128 кбит/с, 44100 Гц: длина кадра 417 байт.
FRAME_LENGTH = 417


def mpeg_frame(*, mono: bool = False, xing: bool = False, tag: bytes = b"Xing") -> bytes:
    """Собрать один кадр MPEG1 Layer III, при желании со служебным тегом."""
    header = bytes([0xFF, 0xFB, 0x90, 0xC0 if mono else 0x00])
    side_info = 17 if mono else 32
    body = bytearray(b"\x00" * (FRAME_LENGTH - 4))
    if xing:
        body[side_info : side_info + 4] = tag
    return header + bytes(body)


def id3v2(payload_size: int = 10) -> bytes:
    """Собрать заголовок ID3v2 с synchsafe-размером."""
    size = bytes(
        [
            (payload_size >> 21) & 0x7F,
            (payload_size >> 14) & 0x7F,
            (payload_size >> 7) & 0x7F,
            payload_size & 0x7F,
        ]
    )
    return b"ID3\x03\x00\x00" + size + b"\x00" * payload_size


def id3v1() -> bytes:
    return b"TAG" + b"\x00" * 125


# ----------------------------------------------------------------------
def test_format_family():
    assert format_family("mp3_44100_128") == "mp3"
    assert format_family("pcm_24000") == "pcm"
    assert format_family("") == "mp3"


def test_extension_for():
    assert extension_for("mp3_44100_128") == ".mp3"
    assert extension_for("wav_44100") == ".wav"
    assert extension_for("что-то_странное") == ".bin"


# ----------------------------------------------------------------------
def test_strip_id3v2_header():
    assert strip_id3(id3v2() + MP3_FRAME) == MP3_FRAME


def test_strip_id3v1_trailer():
    assert strip_id3(MP3_FRAME + id3v1()) == MP3_FRAME


def test_strip_both_tags():
    assert strip_id3(id3v2() + MP3_FRAME + id3v1()) == MP3_FRAME


def test_strip_multiple_id3v2_blocks():
    assert strip_id3(id3v2() + id3v2(4) + MP3_FRAME) == MP3_FRAME


def test_untagged_data_is_untouched():
    assert strip_id3(MP3_FRAME) == MP3_FRAME


def test_empty_input():
    assert strip_id3(b"") == b""


def test_malformed_size_does_not_eat_data():
    # Байт со старшим битом делает synchsafe-размер некорректным.
    broken = b"ID3\x03\x00\x00\xff\x00\x00\x00" + MP3_FRAME
    assert strip_id3(broken) == broken


def test_short_trailer_is_not_mistaken_for_id3v1():
    data = b"TAG" + b"\x00" * 10
    assert strip_id3(data) == data


# ----------------------------------------------------------------------
def test_xing_frame_is_removed():
    audio = mpeg_frame()
    assert strip_xing_header(mpeg_frame(xing=True) + audio) == audio


def test_info_frame_is_removed():
    audio = mpeg_frame()
    assert strip_xing_header(mpeg_frame(xing=True, tag=b"Info") + audio) == audio


def test_xing_frame_in_mono_stream_is_removed():
    audio = mpeg_frame(mono=True)
    assert strip_xing_header(mpeg_frame(mono=True, xing=True) + audio) == audio


def test_ordinary_frame_is_kept():
    audio = mpeg_frame() + mpeg_frame()
    assert strip_xing_header(audio) == audio


def test_tag_at_wrong_offset_is_ignored():
    # «Xing» в середине кадра — совпадение, а не служебный заголовок.
    frame = bytearray(mpeg_frame())
    frame[200:204] = b"Xing"
    data = bytes(frame) + mpeg_frame()
    assert strip_xing_header(data) == data


def test_non_mpeg_data_is_untouched():
    data = "это вообще не mpeg".encode() * 10
    assert strip_xing_header(data) == data


def test_short_input_is_untouched():
    assert strip_xing_header(b"\xff\xfb") == b"\xff\xfb"
    assert strip_xing_header(b"") == b""


def test_free_bitrate_is_untouched():
    frame = bytearray(mpeg_frame(xing=True))
    frame[2] = 0x00  # индекс битрейта 0 — «свободный»
    assert strip_xing_header(bytes(frame)) == bytes(frame)


def test_reserved_sample_rate_is_untouched():
    frame = bytearray(mpeg_frame(xing=True))
    frame[2] = 0x9C  # индекс частоты 3 — зарезервирован
    assert strip_xing_header(bytes(frame)) == bytes(frame)


def test_layer_other_than_three_is_untouched():
    frame = bytearray(mpeg_frame(xing=True))
    frame[1] = 0xFD  # Layer II
    assert strip_xing_header(bytes(frame)) == bytes(frame)


def test_duration_of_single_frame():
    from elevenlabs_voiceover.audio import mp3_duration

    # Кадр MPEG1 Layer III содержит 1152 отсчёта при 44100 Гц.
    assert mp3_duration(mpeg_frame()) == pytest.approx(1152 / 44100)


def test_duration_adds_up_over_frames():
    from elevenlabs_voiceover.audio import mp3_duration

    assert mp3_duration(mpeg_frame() * 10) == pytest.approx(10 * 1152 / 44100)


def test_duration_ignores_service_frame():
    from elevenlabs_voiceover.audio import mp3_duration

    audio = mpeg_frame() * 5
    assert mp3_duration(mpeg_frame(xing=True) + audio) == pytest.approx(mp3_duration(audio))


def test_duration_ignores_id3_tags():
    from elevenlabs_voiceover.audio import mp3_duration

    audio = mpeg_frame() * 3
    assert mp3_duration(id3v2() + audio + id3v1()) == pytest.approx(mp3_duration(audio))


def test_duration_of_non_mpeg_data():
    from elevenlabs_voiceover.audio import mp3_duration

    assert mp3_duration("это не звук".encode() * 50) is None
    assert mp3_duration(b"") is None


def test_duration_survives_damaged_bytes():
    from elevenlabs_voiceover.audio import mp3_duration

    # Мусор между кадрами не должен ни ронять разбор, ни съедать звук.
    damaged = mpeg_frame() + b"\x00\x11\x22" + mpeg_frame()
    assert mp3_duration(damaged) == pytest.approx(2 * 1152 / 44100)


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(None, ""), (-1, ""), (0, "0:00"), (7.4, "0:07"), (65, "1:05"), (600, "10:00"), (3725, "1:02:05")],
)
def test_duration_formatting(seconds, expected):
    from elevenlabs_voiceover.audio import format_duration

    assert format_duration(seconds) == expected


@pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
                    reason="нужен ffmpeg для сверки")
@pytest.mark.parametrize("wanted", [0.5, 2, 9.25])
def test_duration_matches_ffprobe(tmp_path, wanted):
    """Свой расчёт должен совпадать с эталонным измерением."""
    from elevenlabs_voiceover.audio import mp3_duration

    path = tmp_path / "sample.mp3"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
         "-i", "anullsrc=r=44100:cl=mono", "-t", str(wanted), "-b:a", "128k", str(path)],
        check=True,
    )
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True, check=True,
    )

    assert mp3_duration(path.read_bytes()) == pytest.approx(float(probe.stdout), abs=0.03)


def test_concat_drops_xing_from_every_part(tmp_path):
    parts = []
    for index in range(3):
        path = tmp_path / f"{index}.mp3"
        path.write_bytes(mpeg_frame(xing=True) + mpeg_frame())
        parts.append(path)

    target = tmp_path / "out.mp3"
    concat_audio(parts, target, use_ffmpeg=False)

    # Остались только три звуковых кадра, служебные ушли.
    assert target.stat().st_size == FRAME_LENGTH * 3


# ----------------------------------------------------------------------
def test_safe_filename_removes_forbidden_characters():
    assert safe_filename('текст: "часть" <1>/2\\3|4?5*6') == "текст_ _часть_ _1__2_3_4_5_6"


def test_safe_filename_trims_dots_and_spaces():
    assert safe_filename("  имя.  ") == "имя"


def test_safe_filename_handles_reserved_windows_names():
    assert safe_filename("CON") == "_CON"
    assert safe_filename("com1") == "_com1"


def test_safe_filename_truncates():
    assert len(safe_filename("я" * 500)) <= 120


def test_safe_filename_never_returns_empty():
    assert safe_filename("...") == "file"
    assert safe_filename("") == "file"


def test_safe_filename_keeps_cyrillic():
    assert safe_filename("Глава 1 — Начало") == "Глава 1 — Начало"


# ----------------------------------------------------------------------
def test_concat_single_file_is_copied(tmp_path):
    source = tmp_path / "a.mp3"
    source.write_bytes(MP3_FRAME)
    target = tmp_path / "out.mp3"

    concat_audio([source], target, use_ffmpeg=False)
    assert target.read_bytes() == MP3_FRAME


def test_concat_strips_tags_from_following_parts(tmp_path):
    first = tmp_path / "1.mp3"
    second = tmp_path / "2.mp3"
    first.write_bytes(MP3_FRAME)
    second.write_bytes(id3v2() + MP3_FRAME + id3v1())
    target = tmp_path / "out.mp3"

    concat_audio([first, second], target, use_ffmpeg=False)
    assert target.read_bytes() == MP3_FRAME + MP3_FRAME


def test_concat_missing_part_raises(tmp_path):
    present = tmp_path / "1.mp3"
    present.write_bytes(MP3_FRAME)

    with pytest.raises(FileNotFoundError):
        concat_audio([present, tmp_path / "нет.mp3"], tmp_path / "out.mp3", use_ffmpeg=False)


def test_concat_empty_list_raises(tmp_path):
    with pytest.raises(ValueError):
        concat_audio([], tmp_path / "out.mp3", use_ffmpeg=False)


def test_concat_creates_missing_output_directory(tmp_path):
    source = tmp_path / "a.mp3"
    source.write_bytes(MP3_FRAME)
    target = tmp_path / "глубже" / "ещё" / "out.mp3"

    concat_audio([source], target, use_ffmpeg=False)
    assert target.exists()


def test_concat_wav_without_ffmpeg_raises(tmp_path):
    first = tmp_path / "1.wav"
    second = tmp_path / "2.wav"
    first.write_bytes(b"RIFF____WAVE")
    second.write_bytes(b"RIFF____WAVE")

    with pytest.raises(RuntimeError, match="ffmpeg"):
        concat_audio([first, second], tmp_path / "out.wav",
                     output_format="wav_44100", use_ffmpeg=False)
