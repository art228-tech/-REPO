"""Утилиты работы с медиа через ffprobe/ffmpeg."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from ..logging_setup import get_logger

log = get_logger("montage.media")


def ffmpeg_bin() -> str:
    return shutil.which("ffmpeg") or "ffmpeg"


def ffprobe_bin() -> str:
    return shutil.which("ffprobe") or "ffprobe"


def probe_duration(path: str | Path) -> float:
    """Длительность медиафайла в секундах (0.0 при ошибке — не роняем)."""
    try:
        out = subprocess.run(
            [ffprobe_bin(), "-v", "error", "-show_entries",
             "format=duration", "-of", "json", str(path)],
            capture_output=True, text=True, timeout=30, check=True,
        )
        return float(json.loads(out.stdout)["format"]["duration"])
    except (subprocess.SubprocessError, KeyError, ValueError, json.JSONDecodeError) as exc:
        log.warning("Не удалось получить длительность %s: %s", path, exc)
        return 0.0


def run_ffmpeg(args: list[str], timeout: int = 1800) -> None:
    """Запустить ffmpeg, при ошибке кинуть с последними строками лога."""
    cmd = [ffmpeg_bin(), "-hide_banner", "-y", *args]
    log.debug("ffmpeg %s", " ".join(cmd[1:]))
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.strip().splitlines()[-15:])
        raise RuntimeError(f"ffmpeg завершился с ошибкой:\n{tail}")
