"""Нарезка длинного видео на клипы.

Отдельный инструмент, который не участвует в сборке роликов. Нужен, чтобы
готовить материал: обрезать начало и конец записи и порезать остаток на
фрагменты. Длины задаются схемой — либо одинаковые куски, либо чередование,
например четыре секунды, пятнадцать, снова четыре и так до конца.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import ffmpeg
from .errors import PipelineError
from .logging_setup import get_logger

log = get_logger("splitter")

Progress = Callable[[int, int, str], None]


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
    output_dir: Path
    pieces: list[Piece] = field(default_factory=list)
    files: list[Path] = field(default_factory=list)
    skipped_tail_s: float = 0.0

    def summary(self) -> str:
        lengths: dict[float, int] = {}
        for piece in self.pieces:
            lengths[round(piece.requested_s, 3)] = lengths.get(round(piece.requested_s, 3), 0) + 1
        parts = ", ".join(f"{count} шт по {length:g}с" for length, count in sorted(lengths.items()))
        lines = [f"Нарезано {len(self.files)} клипов из {self.source.name}: {parts}"]
        if self.skipped_tail_s > 0:
            lines.append(f"Остаток {self.skipped_tail_s:.2f}с отброшен — на целый фрагмент не хватило")
        lines.append(f"Папка: {self.output_dir}")
        return "\n".join(lines)


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
    output_dir: Path,
    pattern: list[float],
    trim_start_s: float = 0.0,
    trim_end_s: float = 0.0,
    keep_tail: bool = False,
    reencode: bool = True,
    crf: int = 20,
    progress: Progress | None = None,
) -> SplitReport:
    """Режет видео и складывает клипы в указанную папку."""
    ffmpeg.require_tools()
    source = Path(source)
    if not source.is_file():
        raise PipelineError(f"Файл не найден: {source}")

    info = ffmpeg.probe(source)
    pieces, tail = plan_cuts(info.duration_s, pattern, trim_start_s, trim_end_s, keep_tail)
    if not pieces:
        raise PipelineError("Не получилось ни одного фрагмента — уменьши длину или обрезку")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    report = SplitReport(source=source, output_dir=output_dir, pieces=pieces, skipped_tail_s=tail)

    log.info(
        "Режу %s (%.2fс): %d фрагментов по схеме %s, обрезка %g/%g с",
        source.name, info.duration_s, len(pieces),
        "+".join(f"{value:g}" for value in pattern), trim_start_s, trim_end_s,
    )

    total = len(pieces)
    for position, piece in enumerate(pieces, start=1):
        name = f"{source.stem}_{piece.index:03d}_{piece.requested_s:g}s{source.suffix.lower() or '.mp4'}"
        destination = output_dir / name
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
