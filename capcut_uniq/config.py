"""Настройки партии.

Значения по умолчанию взяты из замеров шести исходных шаблонов, чтобы
сгенерированный ролик попадал в те же диапазоны, что и собранный вручную.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from fractions import Fraction
from pathlib import Path

from .errors import PipelineError

# Сдвиг рамки по умолчанию: треть ширины кадра. Две трети прежнего кадра
# остаются на месте, треть приходит с той стороны, которая в обычном ролике
# обрезана.
DEFAULT_FRAME_SHIFT = 1 / 3

# Больше половины ширины сдвигать бессмысленно: столько запаса по бокам не
# бывает даже у самого широкого клипа, и сдвиг всё равно упрётся в его край.
MAX_FRAME_SHIFT = 0.5


def parse_shift(value: str | float) -> float:
    """Разбирает величину сдвига кадра: «1/3», «1/4», «0.25», «25%».

    Доли удобнее процентов, потому что пользователь думает именно ими: «сдвинуть
    на треть». Но принимаем все три записи, чтобы не заставлять пересчитывать.
    """
    if isinstance(value, (int, float)):
        share = float(value)
    else:
        text = str(value).strip().replace(",", ".")
        if not text:
            return DEFAULT_FRAME_SHIFT
        try:
            if text.endswith("%"):
                share = float(text[:-1]) / 100.0
            elif "/" in text:
                share = float(Fraction(text))
            else:
                share = float(text)
        except (ValueError, ZeroDivisionError) as exc:
            raise PipelineError(
                f"«{value}» не похоже на величину сдвига. Задай долю ширины кадра "
                "(«1/3», «1/4»), число («0.25») или проценты («25%»)"
            ) from exc

    if share < 0:
        raise PipelineError("Сдвиг кадра не может быть отрицательным: сторону выбирает программа")
    if share > MAX_FRAME_SHIFT:
        raise PipelineError(
            f"Сдвиг {share:.0%} больше половины ширины кадра — столько запаса по бокам "
            "у клипа не бывает. Возьми 1/2 или меньше"
        )
    return share


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
    # На сколько можно растянуть клип замедлением, если он чуть короче слота.
    # Нарезка на куски по 15с даёт файлы ровно 15.00с, а слот бывает 15.15с —
    # выбрасывать из-за такой малости целую озвучку незачем: замедление на
    # процент в кадре не видно.
    max_clip_stretch: float = 0.06


@dataclass
class Config:
    clips_dir: Path | list[Path]
    """Одна папка с клипами или несколько — например когда короткие и длинные
    разложены нарезкой по разным папкам."""

    voice_dir: Path
    templates: list[str] = field(default_factory=list)
    count: int = 1
    seed: int | None = None
    fps: float = 60.0

    drafts_dir: Path = field(default_factory=_default_drafts_dir)
    work_dir: Path = field(default_factory=lambda: Path.cwd() / "capcut_uniq_data")
    name_prefix: str = "auto"

    # Сколько роликов из каждых шести собрать без размытого фона: вместо копии
    # клипа под наложением остаётся чёрное поле. Считается по шестёркам, чтобы
    # доля держалась при любом размере партии.
    black_bg_of_six: int = 0

    # Сколько роликов делать из одного набора клипов. Клип шире кадра, по бокам
    # у него остаётся неиспользованная картинка, и сдвиг рамки её открывает.
    # 1 — обычная сборка, один ролик на набор. 2 — только сдвинутые влево и
    # вправо: обычный кадр отпадает, зато оба ролика показывают разное. 3 — плюс
    # обычный кадр посередине.
    frames_per_set: int = 1

    # Насколько сдвигать рамку — доля ширины кадра. Чем сдвиг больше, тем сильнее
    # ролики отличаются друг от друга, но тем шире кадра должен быть клип: сдвиг
    # требует масштаба хотя бы 1 + 2 × доля, иначе упрётся в край картинки.
    frame_shift: float = DEFAULT_FRAME_SHIFT

    # Случайные имена проектов вместо «префикс_дата_номер»: русские и английские
    # буквы и цифры, регистр вперемешку.
    random_names: bool = False
    name_length: int = 10

    make_subtitles: bool = True
    # Как записывать субтитр. «простой» — обычный текстовый материал: проверено,
    # что CapCut рисует в нём наш текст. «шаблонный» — через текстовый шаблон,
    # как в исходном проекте: оформление богаче, но текст в кадре не появляется.
    subtitle_device: str = "простой"
    asr_model: str = "small"
    asr_language: str = "ru"
    consume_inputs: bool = True

    ranges: Ranges = field(default_factory=Ranges)
    timing: Timing = field(default_factory=Timing)

    @property
    def clip_folders(self) -> list[Path]:
        value = self.clips_dir
        if isinstance(value, (str, Path)):
            return [Path(value)]
        return [Path(item) for item in value]

    @property
    def log_dir(self) -> Path:
        return self.work_dir / "logs"

    @property
    def used_dir(self) -> Path:
        return self.work_dir / "использовано"

    def to_json(self) -> str:
        data = asdict(self)
        data["clips_dir"] = [str(item) for item in self.clip_folders]
        for key in ("voice_dir", "drafts_dir", "work_dir"):
            data[key] = str(data[key])
        return json.dumps(data, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, path: Path) -> "Config":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        ranges = Ranges(**raw.pop("ranges", {}) or {})
        timing = Timing(**raw.pop("timing", {}) or {})
        if isinstance(raw.get("clips_dir"), list):
            raw["clips_dir"] = [Path(item) for item in raw["clips_dir"]]
        elif raw.get("clips_dir"):
            raw["clips_dir"] = Path(raw["clips_dir"])
        for key in ("voice_dir", "drafts_dir", "work_dir"):
            if raw.get(key):
                raw[key] = Path(raw[key])
        return cls(ranges=ranges, timing=timing, **raw)

    def save(self, path: Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(self.to_json(), encoding="utf-8")
