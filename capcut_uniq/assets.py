"""Пулы входных материалов: нарезанные клипы и озвучки.

Клипы берутся любые, лишь бы хватало длины под слот. Использованные файлы
уводятся в отдельную папку, чтобы не попасться повторно.
"""
from __future__ import annotations

import random
import shutil
from dataclasses import dataclass
from pathlib import Path

from .errors import AssetShortage
from .ffmpeg import probe
from .logging_setup import get_logger

log = get_logger("assets")

VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v", ".mkv", ".avi", ".webm"}
AUDIO_SUFFIXES = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}


@dataclass
class Clip:
    path: Path
    duration_s: float


class Pool:
    """Список файлов с длительностями и учётом уже использованных.

    Папок может быть несколько: нарезка умеет раскладывать короткие и длинные
    клипы по разным папкам, и тогда конвейер берёт материал из всех сразу.
    """

    def __init__(self, folders, suffixes: set[str], kind: str):
        if isinstance(folders, (str, Path)):
            folders = [folders]
        self.folders = [Path(item) for item in folders]
        self.kind = kind

        missing = [folder for folder in self.folders if not folder.is_dir()]
        if missing:
            raise AssetShortage(
                "Папка с материалами не найдена: " + ", ".join(str(item) for item in missing)
            )

        files: list[Path] = []
        for folder in self.folders:
            files.extend(sorted(
                path for path in folder.iterdir()
                if path.is_file() and path.suffix.lower() in suffixes
            ))
        if not files:
            where = ", ".join(str(item) for item in self.folders)
            raise AssetShortage(f"В папке {where} нет подходящих файлов ({kind})")

        self.items: list[Clip] = []
        for path in files:
            try:
                info = probe(path)
            except Exception as exc:  # noqa: BLE001 - файл просто пропускаем
                log.warning("Пропускаю %s: %s", path.name, exc)
                continue
            self.items.append(Clip(path=path, duration_s=info.duration_s))

        log.info("%s: найдено %d файлов в %s", kind, len(self.items),
                 ", ".join(str(item) for item in self.folders))

    def _where(self) -> str:
        return ", ".join(str(item) for item in self.folders)

    def __len__(self) -> int:
        return len(self.items)

    def shuffle(self, rng: random.Random) -> None:
        rng.shuffle(self.items)

    def take_longest_enough(self, needed_s: float) -> Clip:
        """Берёт первый подходящий по длине клип, самый короткий из достаточных.

        Так длинные клипы остаются для длинных слотов и пул расходуется ровнее.
        """
        candidates = [item for item in self.items if item.duration_s + 1e-3 >= needed_s]
        if not candidates:
            longest = max((item.duration_s for item in self.items), default=0.0)
            raise AssetShortage(
                f"Нет клипа длиной хотя бы {needed_s:.2f}с — самый длинный из оставшихся {longest:.2f}с. "
                f"Добавь файлы в {self._where()}"
            )
        chosen = min(candidates, key=lambda item: item.duration_s)
        self.items.remove(chosen)
        return chosen

    def take_next(self) -> Clip:
        if not self.items:
            raise AssetShortage(f"Закончились файлы в {self._where()} ({self.kind})")
        return self.items.pop(0)


def consume(paths: list[Path], used_dir: Path) -> list[Path]:
    """Переносит использованные файлы в отдельную папку.

    Именно переносит, а не удаляет: если партию придётся пересобрать, исходники
    останутся на месте. Повторно они всё равно не попадутся.
    """
    used_dir.mkdir(parents=True, exist_ok=True)
    moved: list[Path] = []
    for path in paths:
        if not path.exists():
            continue
        destination = used_dir / path.name
        counter = 1
        while destination.exists():
            destination = used_dir / f"{path.stem}_{counter}{path.suffix}"
            counter += 1
        shutil.move(str(path), str(destination))
        moved.append(destination)
    if moved:
        log.debug("перенесено в использованные: %s", ", ".join(p.name for p in moved))
    return moved
