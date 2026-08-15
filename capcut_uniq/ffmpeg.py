"""Обёртки над ffprobe и ffmpeg.

Нужны для трёх вещей: узнать параметры клипа, узнать длительность озвучки и
найти тишину в её конце.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .errors import ToolMissing
from .logging_setup import get_logger

log = get_logger("ffmpeg")


def _use_bundled_ffmpeg() -> None:
    """Подхватывает FFmpeg, положенный рядом с программой в папку tools.

    Установщик кладёт его туда, чтобы не менять системные настройки и не
    требовать прав администратора. Раз FFmpeg лежит локально, найти его должна
    сама программа, а не переменная PATH пользователя.
    """
    root = Path(__file__).resolve().parents[1]
    tools = root / "tools"
    candidates = [tools / "ffmpeg" / "bin", tools / "ffmpeg"]
    if tools.is_dir():
        for item in sorted(tools.iterdir()):
            if item.is_dir() and "ffmpeg" in item.name.lower():
                candidates.extend([item / "bin", item])

    for folder in candidates:
        if not folder.is_dir():
            continue
        if (folder / "ffmpeg.exe").exists() or (folder / "ffmpeg").exists():
            current = os.environ.get("PATH", "")
            if str(folder) not in current:
                os.environ["PATH"] = f"{folder}{os.pathsep}{current}"
            return


_use_bundled_ffmpeg()

_SILENCE_START = re.compile(r"silence_start:\s*(-?[\d.]+)")
_SILENCE_END = re.compile(r"silence_end:\s*(-?[\d.]+)")


@dataclass
class MediaInfo:
    path: Path
    duration_s: float
    width: int = 0
    height: int = 0
    has_audio: bool = False
    has_video: bool = False
    fps: float = 0.0

    @property
    def is_image(self) -> bool:
        return self.has_video and self.duration_s <= 0


def require_tools() -> None:
    for tool in ("ffprobe", "ffmpeg"):
        if shutil.which(tool) is None:
            raise ToolMissing(
                f"Не найден {tool}. Установи FFmpeg и добавь его в переменную PATH, "
                "иначе нельзя ни измерить клипы, ни разобрать озвучку."
            )


def _run(args: list[str]) -> subprocess.CompletedProcess:
    log.debug("запуск: %s", " ".join(args))
    return subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace")


def probe(path: Path) -> MediaInfo:
    """Читает параметры файла. Кидает ToolMissing, если ffprobe недоступен."""
    require_tools()
    proc = _run([
        "ffprobe", "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", str(path),
    ])
    if proc.returncode != 0:
        raise ToolMissing(f"ffprobe не смог прочитать файл {path.name}: {proc.stderr.strip()[:200]}")

    data = json.loads(proc.stdout or "{}")
    info = MediaInfo(path=path, duration_s=0.0)

    fmt_duration = (data.get("format") or {}).get("duration")
    if fmt_duration:
        info.duration_s = float(fmt_duration)

    for stream in data.get("streams", []):
        kind = stream.get("codec_type")
        if kind == "video" and not info.has_video:
            info.has_video = True
            info.width = int(stream.get("width") or 0)
            info.height = int(stream.get("height") or 0)
            info.fps = _parse_fps(stream.get("avg_frame_rate") or stream.get("r_frame_rate") or "0/1")
            if not info.duration_s and stream.get("duration"):
                info.duration_s = float(stream["duration"])
        elif kind == "audio":
            info.has_audio = True
            if not info.duration_s and stream.get("duration"):
                info.duration_s = float(stream["duration"])

    log.debug(
        "%s: %.3fс %dx%d fps=%.2f звук=%s",
        path.name, info.duration_s, info.width, info.height, info.fps, info.has_audio,
    )
    return info


def _parse_fps(value: str) -> float:
    try:
        num, _, den = value.partition("/")
        den_value = float(den or 1)
        # У записей экрана в поле частоты нередко стоит мусор вроде 90000/1.
        fps = float(num) / den_value if den_value else 0.0
        return fps if 0 < fps <= 480 else 0.0
    except (TypeError, ValueError):
        return 0.0


def silences(path: Path, threshold_db: float = -38.0, min_len_s: float = 0.05) -> list[tuple[float, float]]:
    """Все интервалы тишины в файле. Последний может быть незакрытым — тогда он до конца."""
    require_tools()
    proc = _run([
        "ffmpeg", "-hide_banner", "-nostats", "-i", str(path),
        "-af", f"silencedetect=noise={threshold_db}dB:d={min_len_s}",
        "-f", "null", "-",
    ])
    output = proc.stderr or ""
    starts = [float(m) for m in _SILENCE_START.findall(output)]
    ends = [float(m) for m in _SILENCE_END.findall(output)]

    total = probe(path).duration_s
    intervals: list[tuple[float, float]] = []
    for index, start in enumerate(starts):
        end = ends[index] if index < len(ends) else total
        intervals.append((start, end))
    return intervals


def trailing_silence(path: Path, threshold_db: float = -38.0, min_len_s: float = 0.05) -> float:
    """Длина тишины в самом конце файла в секундах.

    Ноль означает, что запись обрывается на звуке — тогда хвост не режем.
    """
    intervals = silences(path, threshold_db, min_len_s)
    if not intervals:
        return 0.0

    total = probe(path).duration_s
    last_start, last_end = intervals[-1]
    if last_end < total - 1e-3:
        return 0.0

    tail = max(0.0, total - last_start)
    log.debug("%s: тишина в конце %.3fс", path.name, tail)
    return tail
