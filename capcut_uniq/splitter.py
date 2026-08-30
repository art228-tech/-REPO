"""Нарезка длинного видео на клипы.

Отдельный инструмент, который не участвует в сборке роликов. Нужен, чтобы
готовить материал: обрезать начало и конец записи и порезать остаток на
фрагменты. Длины задаются схемой — либо одинаковые куски, либо чередование,
например четыре секунды, пятнадцать, снова четыре и так до конца.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Mapping

from . import ffmpeg
from .errors import PipelineError
from .logging_setup import get_logger

log = get_logger("splitter")

Progress = Callable[[int, int, str], None]


def key(length: float) -> float:
    """Округлённая длина — ей адресуется папка вывода."""
    return round(float(length), 3)


@dataclass
class Piece:
    index: int
    start_s: float
    duration_s: float
    requested_s: float

    @property
    def is_short(self) -> bool:
        return self.duration_s + 1e-3 < self.requested_s


@dataclass
class SplitReport:
    source: Path
    targets: dict[float, Path] = field(default_factory=dict)
    pieces: list[Piece] = field(default_factory=list)
    files: list[Path] = field(default_factory=list)
    skipped_tail_s: float = 0.0

    def summary(self) -> str:
        counts: dict[float, int] = {}
        for piece in self.pieces:
            counts[key(piece.requested_s)] = counts.get(key(piece.requested_s), 0) + 1

        lines = [f"Нарезано {len(self.files)} клипов из {self.source.name}"]
        for length in sorted(counts):
            folder = self.targets.get(length)
            lines.append(f"  по {length:g}с — {counts[length]} шт → {folder}")
        if self.skipped_tail_s > 0:
            lines.append(f"Остаток {self.skipped_tail_s:.2f}с отброшен — на целый фрагмент не хватило")
        return "\n".join(lines)


def pattern_lengths(pattern: list[float]) -> list[float]:
    """Различные длины в порядке первого появления в схеме."""
    result: list[float] = []
    for value in pattern:
        rounded = key(value)
        if rounded not in result:
            result.append(rounded)
    return result


def resolve_targets(pattern: list[float], folders) -> dict[float, Path]:
    """Сопоставляет длины фрагментов папкам вывода.

    Одна папка — всё складывается вместе. Несколько — по числу различных длин,
    в том же порядке, в каком они идут в схеме: для «4 15» первая папка
    достаётся четырёхсекундным, вторая — пятнадцатисекундным.
    """
    lengths = pattern_lengths(pattern)

    if isinstance(folders, Mapping):
        missing = [length for length in lengths if key(length) not in {key(k) for k in folders}]
        if missing:
            raise PipelineError(
                "Не указана папка для фрагментов длиной "
                + ", ".join(f"{value:g}с" for value in missing)
            )
        return {key(length): Path(folders[length]) for length in lengths}

    if isinstance(folders, (str, Path)):
        folders = [folders]
    folders = [Path(item) for item in folders if str(item).strip()]

    if not folders:
        raise PipelineError("Не указана папка, куда складывать клипы")
    if len(folders) == 1:
        return {key(length): folders[0] for length in lengths}
    if len(folders) != len(lengths):
        raise PipelineError(
            f"В схеме {len(lengths)} разных длин, а папок указано {len(folders)}. "
            "Укажи либо одну общую папку, либо по одной на каждую длину."
        )
    return {key(length): folder for length, folder in zip(lengths, folders)}


def parse_pattern(text: str) -> list[float]:
    """Разбирает схему длин: «4», «4 15», «4, 15, 4»."""
    raw = [part for part in text.replace(",", " ").replace(";", " ").split() if part]
    if not raw:
        raise PipelineError("Не задана длина фрагментов")

    pattern: list[float] = []
    for part in raw:
        try:
            value = float(part.replace(",", "."))
        except ValueError as exc:
            raise PipelineError(f"«{part}» не похоже на число секунд") from exc
        if value <= 0:
            raise PipelineError("Длина фрагмента должна быть больше нуля")
        pattern.append(value)
    return pattern


def plan_cuts(
    duration_s: float,
    pattern: list[float],
    trim_start_s: float = 0.0,
    trim_end_s: float = 0.0,
    keep_tail: bool = False,
    min_piece_s: float = 0.5,
) -> tuple[list[Piece], float]:
    """Считает, какие куски вырезать. Возвращает список и длину отброшенного хвоста."""
    if duration_s <= 0:
        raise PipelineError("Не удалось определить длину видео")

    begin = max(0.0, trim_start_s)
    end = duration_s - max(0.0, trim_end_s)
    if end - begin <= min_piece_s:
        raise PipelineError(
            f"После обрезки не остаётся материала: было {duration_s:.2f}с, "
            f"срезано {trim_start_s:g}с с начала и {trim_end_s:g}с с конца"
        )

    pieces: list[Piece] = []
    position = begin
    index = 0
    while position < end - 1e-6:
        requested = pattern[index % len(pattern)]
        remaining = end - position

        if remaining + 1e-6 < requested:
            if not keep_tail or remaining < min_piece_s:
                return pieces, remaining
            pieces.append(Piece(index=index + 1, start_s=position,
                                duration_s=remaining, requested_s=requested))
            return pieces, 0.0

        pieces.append(Piece(index=index + 1, start_s=position,
                            duration_s=requested, requested_s=requested))
        position += requested
        index += 1

    return pieces, 0.0


def split(
    source: Path,
    folders,
    pattern: list[float],
    trim_start_s: float = 0.0,
    trim_end_s: float = 0.0,
    keep_tail: bool = False,
    reencode: bool = True,
    crf: int = 20,
    progress: Progress | None = None,
) -> SplitReport:
    """Режет видео и раскладывает клипы по папкам согласно длинам."""
    ffmpeg.require_tools()
    source = Path(source)
    if not source.is_file():
        raise PipelineError(f"Файл не найден: {source}")

    targets = resolve_targets(pattern, folders)

    info = ffmpeg.probe(source)
    pieces, tail = plan_cuts(info.duration_s, pattern, trim_start_s, trim_end_s, keep_tail)
    if not pieces:
        raise PipelineError("Не получилось ни одного фрагмента — уменьши длину или обрезку")

    for folder in set(targets.values()):
        folder.mkdir(parents=True, exist_ok=True)
    report = SplitReport(source=source, targets=targets, pieces=pieces, skipped_tail_s=tail)

    log.info(
        "Режу %s (%.2fс): %d фрагментов по схеме %s, обрезка %g/%g с",
        source.name, info.duration_s, len(pieces),
        "+".join(f"{value:g}" for value in pattern), trim_start_s, trim_end_s,
    )
    for length in sorted(targets):
        log.debug("  фрагменты по %g с → %s", length, targets[length])

    # Нумерация продолжается с той, что уже лежит в папках. Без этого повторная
    # нарезка того же видео давала те же имена и затирала прежние клипы: восемь
    # прогонов по одному файлу оставляли материал только последнего.
    suffix = source.suffix.lower() or ".mp4"
    offset = _last_index(source.stem, suffix, set(targets.values()))
    if offset:
        log.info("В папках уже есть клипы из этого видео, продолжаю нумерацию с %d",
                 offset + 1)

    total = len(pieces)
    for position, piece in enumerate(pieces, start=1):
        folder = targets[key(piece.requested_s)]
        number = piece.index + offset
        name = f"{source.stem}_{number:03d}_{piece.requested_s:g}s{suffix}"
        # Подстраховка: если такое имя всё же занято, отступаем дальше.
        while (folder / name).exists():
            number += 1
            name = f"{source.stem}_{number:03d}_{piece.requested_s:g}s{suffix}"
        destination = folder / name
        if progress:
            progress(position, total, f"фрагмент {position} из {total}: {name}")

        _cut(source, destination, piece, reencode, crf)
        if not destination.exists() or destination.stat().st_size == 0:
            raise PipelineError(f"Не удалось вырезать фрагмент {position}: {name}")

        report.files.append(destination)
        log.debug("  %s: %.3f→%.3f (%.3fс)", name, piece.start_s,
                  piece.start_s + piece.duration_s, piece.duration_s)

    log.info("%s", report.summary())
    return report


def _last_index(stem: str, suffix: str, folders: set[Path]) -> int:
    """Самый большой номер клипа из этого видео среди уже нарезанных."""
    pattern = re.compile(rf"^{re.escape(stem)}_(\d+)_[\d.]+s{re.escape(suffix)}$",
                         re.IGNORECASE)
    highest = 0
    for folder in folders:
        if not folder.is_dir():
            continue
        for item in folder.iterdir():
            found = pattern.match(item.name)
            if found:
                highest = max(highest, int(found.group(1)))
    return highest


def _cut(source: Path, destination: Path, piece: Piece, reencode: bool, crf: int) -> None:
    args = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-ss", f"{piece.start_s:.3f}", "-i", str(source),
        "-t", f"{piece.duration_s:.3f}",
    ]
    if reencode:
        # Перекодирование даёт точную длину. Копирование потока быстрее, но
        # прыгает по опорным кадрам, и фрагмент может выйти короче заказанного.
        args += ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf),
                 "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k"]
    else:
        args += ["-c", "copy"]
    args += ["-movflags", "+faststart", str(destination)]

    result = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        raise PipelineError(
            f"ffmpeg не смог вырезать фрагмент {piece.index}: {result.stderr.strip()[:200]}"
        )
