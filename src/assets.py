"""Менеджер папок-ассетов.

Структура папок (создаётся рядом с софтом в каталоге «Ассеты»):

    Ассеты/
        Музыка 1 (переход)/          — звук перехода в начале        [СЛУЧАЙНО]
        Музыка 2 (перед наложениями)/ — звук перед видео-наложением и фото [СЛУЧАЙНО]
        Озвучка/                      — озвучка (музыка #3)           [РАСХОД]
        Фон 1 (вступление)/           — короткий вступительный фон    [РАСХОД]
        Фон 2 (основной)/             — основной игровой фон          [РАСХОД]
        Видео наложение/              — видео-наложение в середине    [СЛУЧАЙНО]
        Результат/                    — сюда экспортируются готовые ролики

Режимы:
    СЛУЧАЙНО (RANDOM) — файл выбирается случайно и остаётся в папке.
    РАСХОД  (CONSUME) — файл выбирается и «уходит» из папки (переносится в
             подпапку _использовано), чтобы следующий ролик взял другой файл.
             Перенос вместо удаления — чтобы случайно не потерять исходники.

Фоновая музыка и фото в конце как контент НЕ берутся из папок: они остаются
из исходного проекта CapCut (фоновую музыку софт только подрезает по длине).
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .logging_setup import get_logger

logger = get_logger()

AUDIO_EXT = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}
VIDEO_EXT = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}

ARCHIVE_SUBDIR = "_использовано"


class Mode(Enum):
    RANDOM = "random"
    CONSUME = "consume"


class MediaKind(Enum):
    AUDIO = "audio"
    VIDEO = "video"


@dataclass(frozen=True)
class FolderSpec:
    key: str            # внутренний идентификатор
    folder_name: str    # имя папки на диске
    mode: Mode
    kind: MediaKind
    description: str


# Порядок = порядок замены на таймлайне (см. pipeline).
FOLDERS: list[FolderSpec] = [
    FolderSpec("music_transition", "Музыка 1 (переход)", Mode.RANDOM, MediaKind.AUDIO,
               "Звук перехода в начале"),
    FolderSpec("music_overlay", "Музыка 2 (перед наложениями)", Mode.RANDOM, MediaKind.AUDIO,
               "Звук перед видео-наложением и перед фото в конце"),
    FolderSpec("voiceover", "Озвучка", Mode.CONSUME, MediaKind.AUDIO,
               "Озвучка (музыка #3) — задаёт итоговую длину ролика"),
    FolderSpec("background_intro", "Фон 1 (вступление)", Mode.CONSUME, MediaKind.VIDEO,
               "Короткий вступительный игровой фон"),
    FolderSpec("background_main", "Фон 2 (основной)", Mode.CONSUME, MediaKind.VIDEO,
               "Основной игровой фон"),
    FolderSpec("overlay_video", "Видео наложение", Mode.RANDOM, MediaKind.VIDEO,
               "Видео-наложение в середине ролика"),
]

RESULT_FOLDER_NAME = "Результат"

FOLDERS_BY_KEY: dict[str, FolderSpec] = {f.key: f for f in FOLDERS}


class AssetError(Exception):
    """Ошибка ассетов (например, не хватает файлов на запрошенное число циклов)."""


def _allowed_ext(kind: MediaKind) -> set[str]:
    return AUDIO_EXT if kind == MediaKind.AUDIO else VIDEO_EXT


class AssetManager:
    def __init__(self, assets_root: Path) -> None:
        self.root = Path(assets_root)

    # ---- структура ----

    def ensure_folders(self) -> None:
        """Создаёт все папки, если их ещё нет."""
        self.root.mkdir(parents=True, exist_ok=True)
        for spec in FOLDERS:
            (self.root / spec.folder_name).mkdir(exist_ok=True)
        (self.root / RESULT_FOLDER_NAME).mkdir(exist_ok=True)
        logger.info("Папки-ассеты готовы: %s", self.root)

    def folder_path(self, key: str) -> Path:
        return self.root / FOLDERS_BY_KEY[key].folder_name

    def result_path(self) -> Path:
        return self.root / RESULT_FOLDER_NAME

    # ---- содержимое ----

    def list_files(self, key: str) -> list[Path]:
        spec = FOLDERS_BY_KEY[key]
        folder = self.folder_path(key)
        if not folder.exists():
            return []
        exts = _allowed_ext(spec.kind)
        files = [
            p for p in folder.iterdir()
            if p.is_file() and p.suffix.lower() in exts and not p.name.startswith("~")
        ]
        return sorted(files, key=lambda p: p.name.lower())

    def count(self, key: str) -> int:
        return len(self.list_files(key))

    # ---- валидация перед запуском батча ----

    def validate_for_cycles(self, cycles: int) -> None:
        """Проверяет, что файлов хватит на `cycles` роликов.

        RANDOM-папки: нужен минимум 1 файл.
        CONSUME-папки: нужно минимум `cycles` файлов.
        При нехватке — AssetError (пайплайн останавливается и сообщает об ошибке).
        """
        problems: list[str] = []
        for spec in FOLDERS:
            n = self.count(spec.key)
            need = cycles if spec.mode == Mode.CONSUME else 1
            if n < need:
                problems.append(
                    f"«{spec.folder_name}»: есть {n}, нужно минимум {need}"
                    + (f" (на {cycles} циклов)" if spec.mode == Mode.CONSUME else "")
                )
        if problems:
            raise AssetError(
                "Недостаточно файлов для запуска:\n  - " + "\n  - ".join(problems)
            )

    # ---- выбор файла ----

    def pick(self, key: str) -> Path:
        """Выбирает файл согласно режиму папки. Для RANDOM файл остаётся,
        для CONSUME — переносится в подпапку _использовано."""
        spec = FOLDERS_BY_KEY[key]
        files = self.list_files(key)
        if not files:
            raise AssetError(f"Папка «{spec.folder_name}» пуста")

        chosen = random.choice(files)

        if spec.mode == Mode.CONSUME:
            chosen = self._consume(chosen)
            logger.info("[%s] взят и израсходован файл: %s", spec.folder_name, chosen.name)
        else:
            logger.info("[%s] выбран случайный файл: %s", spec.folder_name, chosen.name)
        return chosen

    def _consume(self, file: Path) -> Path:
        archive = file.parent / ARCHIVE_SUBDIR
        archive.mkdir(exist_ok=True)
        target = archive / file.name
        # Избегаем перезаписи при совпадении имён.
        i = 1
        while target.exists():
            target = archive / f"{file.stem}_{i}{file.suffix}"
            i += 1
        file.replace(target)
        return target
