"""Настройки партии.

Значения по умолчанию взяты из замеров шести исходных шаблонов, чтобы
сгенерированный ролик попадал в те же диапазоны, что и собранный вручную.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path


def _default_drafts_dir() -> Path:
    """Папка черновиков CapCut. На Windows и macOS пути разные."""
    import os
    import sys

    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA", "")
        return Path(base) / "CapCut" / "User Data" / "Projects" / "com.lveditor.draft"
    if sys.platform == "darwin":
        return Path.home() / "Movies" / "CapCut" / "User Data" / "Projects" / "com.lveditor.draft"
    return Path.home() / "CapCut" / "User Data" / "Projects" / "com.lveditor.draft"


@dataclass
class Ranges:
    """Диапазоны уникализации. Всё остальное наследуется от шаблона без изменений."""

    # Стикер (смайлик с комбо-анимацией)
    sticker_start_s: tuple[float, float] = (4.0, 8.0)
    sticker_speed: tuple[float, float] = (1.2, 1.4)
    sticker_dy: float = 0.03

    # QR в конце
    qr_before_end_s: tuple[float, float] = (1.0, 2.0)
    qr_dy: float = 0.03

    # Громкость звуков стикера и QR — доля от значения шаблона
    sfx_volume_jitter: float = 0.05

    # Фоновая музыка
    music_volume: tuple[float, float] = (0.05, 0.08)

    # Масштаб резкого наложения — доля от значения шаблона, каждому сегменту своё
    overlay_scale_jitter: float = 0.05


@dataclass
class Timing:
    """Правила раскладки таймлайна."""

    # Коридор для точки стыка короткого и длинного фрагментов
    cut_min_s: float = 1.5
    cut_max_s: float = 4.0
    # Сколько тишины оставить в конце озвучки при обрезке хвоста
    vo_tail_silence_s: float = 0.10
    # Порог тишины для детектора, дБ
    silence_db: float = -38.0
    # Минимальная пауза между словами, которая считается границей субтитра
    subtitle_gap_s: float = 0.35
    # Мягкий предел длины субтитра в символах
    subtitle_max_chars: int = 50


@dataclass
class Config:
    clips_dir: Path
    voice_dir: Path
    templates: list[str] = field(default_factory=list)
    count: int = 1
    seed: int | None = None
    fps: float = 60.0

    drafts_dir: Path = field(default_factory=_default_drafts_dir)
    work_dir: Path = field(default_factory=lambda: Path.cwd() / "capcut_uniq_data")
    name_prefix: str = "auto"

    make_subtitles: bool = True
    asr_model: str = "small"
    asr_language: str = "ru"
    consume_inputs: bool = True

    ranges: Ranges = field(default_factory=Ranges)
    timing: Timing = field(default_factory=Timing)

    @property
    def log_dir(self) -> Path:
        return self.work_dir / "logs"

    @property
    def used_dir(self) -> Path:
        return self.work_dir / "использовано"

    def to_json(self) -> str:
        data = asdict(self)
        for key in ("clips_dir", "voice_dir", "drafts_dir", "work_dir"):
            data[key] = str(data[key])
        return json.dumps(data, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, path: Path) -> "Config":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        ranges = Ranges(**raw.pop("ranges", {}) or {})
        timing = Timing(**raw.pop("timing", {}) or {})
        for key in ("clips_dir", "voice_dir", "drafts_dir", "work_dir"):
            if raw.get(key):
                raw[key] = Path(raw[key])
        return cls(ranges=ranges, timing=timing, **raw)

    def save(self, path: Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(self.to_json(), encoding="utf-8")
