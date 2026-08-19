"""Склейка кусков аудио в один файл.

Если рядом есть ffmpeg — используем его: он корректно пересобирает контейнер.
Без ffmpeg работает запасной путь для MP3: у кусков срезаются ID3-теги, а
кадры складываются подряд. Это безопасно именно здесь, потому что все куски
приходят из одного API с одинаковыми частотой дискретизации и битрейтом.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List, NamedTuple, Optional, Sequence

from .logging_setup import get_logger
from .paths import app_root

log = get_logger("audio")

#: Форматы, которые нельзя просто склеить побайтово.
_NEEDS_FFMPEG = {"wav", "opus"}

_EXTENSIONS = {
    "mp3": ".mp3",
    "pcm": ".pcm",
    "wav": ".wav",
    "opus": ".opus",
    "ulaw": ".ulaw",
    "alaw": ".alaw",
}

_ffmpeg_cache: Optional[str] = None
_ffmpeg_searched = False


def format_family(output_format: str) -> str:
    """Из mp3_44100_128 получить mp3."""
    return (output_format or "mp3").split("_", 1)[0].lower()


def extension_for(output_format: str) -> str:
    return _EXTENSIONS.get(format_family(output_format), ".bin")


def format_family_of_path(path: Path) -> str:
    """Определить формат по расширению файла."""
    suffix = path.suffix.lower().lstrip(".")
    return suffix if suffix in _EXTENSIONS else ""


def find_ffmpeg() -> Optional[str]:
    """Найти ffmpeg: сначала рядом с программой, потом в PATH.

    Класть ffmpeg.exe рядом с программой удобно на Windows, где его обычно нет
    в системе и добавлять его в PATH пользователю не хочется.
    """
    global _ffmpeg_cache, _ffmpeg_searched
    if _ffmpeg_searched:
        return _ffmpeg_cache

    _ffmpeg_searched = True
    binary = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"

    for candidate in (app_root() / binary, app_root() / "ffmpeg" / binary, app_root() / "bin" / binary):
        if candidate.exists() and os.access(candidate, os.X_OK):
            _ffmpeg_cache = str(candidate)
            log.debug("ffmpeg найден рядом с программой: %s", candidate)
            return _ffmpeg_cache

    found = shutil.which("ffmpeg")
    if found:
        log.debug("ffmpeg найден в PATH: %s", found)
    else:
        log.debug("ffmpeg не найден, для MP3 будет использован встроенный склейщик")
    _ffmpeg_cache = found
    return _ffmpeg_cache


def reset_ffmpeg_cache() -> None:
    global _ffmpeg_cache, _ffmpeg_searched
    _ffmpeg_cache = None
    _ffmpeg_searched = False


# ----------------------------------------------------------------------
# ID3
# ----------------------------------------------------------------------
def strip_id3(data: bytes) -> bytes:
    """Убрать теги ID3v2 в начале и ID3v1 в конце.

    Внутри склеенного потока теги превращаются в мусорные байты между кадрами:
    большинство плееров их переживают, но длительность и перемотка ломаются.
    """
    if not data:
        return data

    start = 0
    # ID3v2 может идти несколькими блоками подряд.
    while len(data) - start >= 10 and data[start : start + 3] == b"ID3":
        flags = data[start + 5]
        size_bytes = data[start + 6 : start + 10]
        if any(b & 0x80 for b in size_bytes):
            # Некорректный synchsafe-размер: дальше не разбираем.
            break
        size = 0
        for byte in size_bytes:
            size = (size << 7) | (byte & 0x7F)
        block = 10 + size
        if flags & 0x10:  # присутствует футер
            block += 10
        if block <= 0 or start + block > len(data):
            break
        start += block

    end = len(data)
    if end - start >= 128 and data[end - 128 : end - 125] == b"TAG":
        end -= 128

    return data[start:end]


# Таблицы MPEG Layer III: битрейт в кбит/с и частота дискретизации в Гц.
_BITRATES_V1 = (0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 0)
_BITRATES_V2 = (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 0)
_SAMPLE_RATES = {
    3: (44100, 48000, 32000, 0),  # MPEG 1
    2: (22050, 24000, 16000, 0),  # MPEG 2
    0: (11025, 12000, 8000, 0),   # MPEG 2.5
}


class _Frame(NamedTuple):
    """Разобранный заголовок одного кадра MPEG."""

    length: int
    samples: int
    sample_rate: int
    side_info: int


def _read_frame(data: bytes, pos: int = 0) -> Optional[_Frame]:
    """Разобрать заголовок кадра по смещению. None, если это не кадр."""
    if pos + 4 > len(data):
        return None
    if data[pos] != 0xFF or (data[pos + 1] & 0xE0) != 0xE0:
        return None

    version_bits = (data[pos + 1] >> 3) & 0x03
    layer_bits = (data[pos + 1] >> 1) & 0x03
    if version_bits == 1 or layer_bits != 1:  # только MPEG Layer III
        return None

    bitrate_index = (data[pos + 2] >> 4) & 0x0F
    rate_index = (data[pos + 2] >> 2) & 0x03
    padding = (data[pos + 2] >> 1) & 0x01
    channel_mode = (data[pos + 3] >> 6) & 0x03

    if bitrate_index in (0, 15) or rate_index == 3:
        return None

    bitrates = _BITRATES_V1 if version_bits == 3 else _BITRATES_V2
    bitrate = bitrates[bitrate_index] * 1000
    sample_rate = _SAMPLE_RATES[version_bits][rate_index]
    if not bitrate or not sample_rate:
        return None

    samples = 1152 if version_bits == 3 else 576
    length = (samples // 8) * bitrate // sample_rate + padding
    if length <= 4:
        return None

    mono = channel_mode == 3
    if version_bits == 3:
        side_info = 17 if mono else 32
    else:
        side_info = 9 if mono else 17

    return _Frame(length=length, samples=samples, sample_rate=sample_rate, side_info=side_info)


def _is_service_frame(data: bytes, pos: int, frame: _Frame) -> bool:
    """Кадр Xing/Info: описывает файл целиком, звука не содержит."""
    tag_at = pos + 4 + frame.side_info
    return data[tag_at : tag_at + 4] in (b"Xing", b"Info")


def strip_xing_header(data: bytes) -> bytes:
    """Убрать служебный кадр Xing/Info в начале потока.

    Такой кадр описывает длительность всего файла и звука не содержит. При
    склейке нескольких файлов подряд каждый следующий кадр Xing декодер
    принимает за обычный и добавляет к записи лишние 26 миллисекунд тишины, а
    заголовок первого файла начинает врать о длительности всей склейки.
    Проще выкинуть их все: у потока с постоянным битрейтом длительность и без
    них считается по размеру верно.
    """
    frame = _read_frame(data)
    if frame is None or frame.length > len(data):
        return data
    if not _is_service_frame(data, 0, frame):
        return data
    return data[frame.length :]


def mp3_duration(data: bytes) -> Optional[float]:
    """Длительность записи в секундах, посчитанная по кадрам.

    Считаем сами, а не через ffmpeg: его может не быть на машине, а знать,
    сколько получилось звука, полезно всегда.
    """
    payload = strip_id3(data)
    seconds = 0.0
    frames = 0
    position = 0
    limit = len(payload)

    while position + 4 <= limit:
        frame = _read_frame(payload, position)
        if frame is None:
            # Рассинхронизация: ищем начало следующего кадра побайтно.
            position += 1
            continue
        if not (frames == 0 and _is_service_frame(payload, position, frame)):
            seconds += frame.samples / frame.sample_rate
            frames += 1
        position += frame.length

    return seconds if frames else None


def format_duration(seconds: Optional[float]) -> str:
    """Длительность в виде 1:23 или 1:02:03."""
    if seconds is None or seconds < 0:
        return ""
    total = round(seconds)
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


# ----------------------------------------------------------------------
# Склейка
# ----------------------------------------------------------------------
def concat_audio(
    parts: Sequence[Path],
    destination: Path,
    *,
    output_format: str = "mp3_44100_128",
    use_ffmpeg: bool = True,
) -> Path:
    """Склеить куски в один файл. Возвращает путь к результату."""
    paths = [Path(p) for p in parts]
    missing = [p for p in paths if not p.exists()]
    if missing:
        raise FileNotFoundError(f"Не найдены куски для склейки: {', '.join(str(m) for m in missing[:5])}")
    if not paths:
        raise ValueError("Список кусков пуст")

    destination.parent.mkdir(parents=True, exist_ok=True)

    if len(paths) == 1:
        shutil.copyfile(paths[0], destination)
        return destination

    family = format_family(output_format)
    ffmpeg = find_ffmpeg() if use_ffmpeg else None

    if ffmpeg:
        try:
            return _concat_with_ffmpeg(ffmpeg, paths, destination)
        except Exception as exc:  # noqa: BLE001 - падать из-за склейки нельзя
            log.warning("ffmpeg не смог склеить файл (%s), перехожу на встроенный склейщик", exc)

    if family in _NEEDS_FFMPEG:
        raise RuntimeError(
            f"Для формата {output_format} нужна склейка через ffmpeg, но он не найден. "
            "Положите ffmpeg.exe рядом с программой или выберите формат mp3."
        )

    return _concat_raw(paths, destination, strip_tags=(family == "mp3"))


def _concat_with_ffmpeg(ffmpeg: str, paths: List[Path], destination: Path) -> Path:
    list_file = None
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as handle:
            list_file = Path(handle.name)
            for path in paths:
                escaped = str(path.resolve()).replace("\\", "/").replace("'", r"'\''")
                handle.write(f"file '{escaped}'\n")

        command = [
            ffmpeg,
            "-hide_banner",
            "-loglevel", "error",
            "-nostdin",
            "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(list_file),
            "-c", "copy",
            str(destination),
        ]
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=600,
            creationflags=_no_window_flag(),
        )
        if result.returncode != 0:
            raise RuntimeError((result.stderr or "").strip()[:500] or f"код возврата {result.returncode}")
        if not destination.exists() or destination.stat().st_size == 0:
            raise RuntimeError("ffmpeg отработал, но файл пуст")
        return destination
    finally:
        if list_file and list_file.exists():
            try:
                list_file.unlink()
            except OSError:
                pass


def _concat_raw(paths: List[Path], destination: Path, *, strip_tags: bool) -> Path:
    with destination.open("wb") as out:
        for path in paths:
            data = path.read_bytes()
            if strip_tags:
                # Пустой результат означает, что разбор пошёл не так: лучше
                # записать кусок как есть, чем потерять звук.
                cleaned = strip_id3(data)
                data = strip_xing_header(cleaned) or cleaned or data
            out.write(data)
    return destination


def _no_window_flag() -> int:
    """Не показывать чёрное окно консоли при вызове ffmpeg из GUI на Windows."""
    if sys.platform == "win32":
        return getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return 0


def safe_filename(name: str, *, max_length: int = 120) -> str:
    """Привести имя к виду, который примет файловая система Windows."""
    forbidden = '<>:"/\\|?*'
    cleaned = "".join("_" if ch in forbidden or ord(ch) < 32 else ch for ch in name).strip(" .")

    reserved = {
        "CON", "PRN", "AUX", "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }
    if cleaned.upper() in reserved:
        cleaned = f"_{cleaned}"

    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length].rstrip(" .")

    return cleaned or "file"
