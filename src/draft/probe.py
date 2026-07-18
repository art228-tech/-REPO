"""Определение длительности медиафайла (в микросекундах, как в CapCut).

Пробуем в порядке доступности:
  1. системный ffprobe;
  2. ffmpeg из пакета imageio-ffmpeg (парсим строку Duration).

Длительность нужна, чтобы при замене корректно проставить duration материала
и source_timerange.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

from ..logging_setup import get_logger

logger = get_logger()


class ProbeError(Exception):
    pass


def _ffprobe_bin() -> str | None:
    return shutil.which("ffprobe")


def _ffmpeg_bin() -> str | None:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg  # type: ignore

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001
        return None


def _run(cmd: list[str]) -> tuple[int, str, str]:
    proc = subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    return proc.returncode, proc.stdout, proc.stderr


def probe_duration_us(path: str | Path) -> int:
    """Возвращает длительность файла в микросекундах."""
    path = str(path)
    if not Path(path).exists():
        raise ProbeError(f"Файл не найден: {path}")

    ffprobe = _ffprobe_bin()
    if ffprobe:
        code, out, _ = _run([
            ffprobe, "-v", "quiet", "-print_format", "json",
            "-show_format", path,
        ])
        if code == 0:
            try:
                data = json.loads(out)
                dur = float(data["format"]["duration"])
                return int(round(dur * 1_000_000))
            except (KeyError, ValueError, json.JSONDecodeError):
                pass

    ffmpeg = _ffmpeg_bin()
    if ffmpeg:
        # ffmpeg пишет сведения о длительности в stderr.
        _, _, err = _run([ffmpeg, "-i", path])
        m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", err)
        if m:
            h, mnt, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
            total = h * 3600 + mnt * 60 + s
            return int(round(total * 1_000_000))

    raise ProbeError(
        "Не удалось определить длительность файла. Нужен ffprobe или ffmpeg "
        "(устанавливается вместе с imageio-ffmpeg из requirements.txt)."
    )
