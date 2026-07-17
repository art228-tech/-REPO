"""Менеджер материалов: выбор следующего файла с учётом режима папки и
пометкой «использовано». Плюс учёт использованных секунд фонового видео.

Режимы (как просил пользователь):
  * cycle   — прошли все файлы в папке и снова по кругу;
  * consume — использовали файл и удалили его из папки.

Учёт состояния ведётся через StateStore, поэтому переживает перезапуск.
"""
from __future__ import annotations

import random
from pathlib import Path

from .config import FolderRule
from .logging_setup import get_logger
from .state import StateStore

log = get_logger("assets")

_AUDIO = {".mp3", ".wav", ".m4a", ".ogg"}

# Что считаем «файлом-материалом» в каждой категории.
DEFAULT_EXTS = {
    "voice_prompts": {".txt"},
    "scripts": {".txt"},
    "backgrounds": {".mp4", ".mov", ".mkv", ".webm"},
    "emojis": {".png", ".webp", ".gif"},
    "sounds_swoosh": _AUDIO,
    "sounds_accent": _AUDIO,
    "sounds": _AUDIO,
    "qr": {".png", ".jpg", ".jpeg", ".webp"},
    "music": _AUDIO,
    "fonts": {".ttf", ".otf"},
}


class AssetPool:
    """Один пул = одна папка-категория с правилом выбора."""

    def __init__(self, name: str, rule: FolderRule, state: StateStore,
                 exts: set[str] | None = None):
        self.name = name
        self.rule = rule
        self.state = state
        self.dir = Path(rule.path)
        self.exts = exts or DEFAULT_EXTS.get(name, set())

    def _scan(self) -> list[Path]:
        if not self.dir.exists():
            return []
        files = [
            p for p in sorted(self.dir.iterdir())
            if p.is_file() and (not self.exts or p.suffix.lower() in self.exts)
        ]
        return files

    def count(self) -> int:
        return len(self._scan())

    def _cursor_key(self) -> str:
        return f"cursor:{self.name}"

    def next(self) -> Path | None:
        """Вернуть следующий материал согласно режиму.

        cycle:   идём по кругу, курсор хранится в state.
        consume: берём первый и физически удаляем его после возврата вызовом
                 mark_consumed(); тут только выдаём первый доступный.
        Возвращает None, если папка пуста.
        """
        files = self._scan()
        if not files:
            log.warning("Папка '%s' (%s) пуста — нечего брать.", self.name,
                        self.dir)
            return None

        if self.rule.mode == "consume":
            return files[0]

        # cycle
        idx = int(self.state.get(self._cursor_key(), 0)) % len(files)
        chosen = files[idx]
        self.state.set(self._cursor_key(), (idx + 1) % len(files))
        return chosen

    def pick_random(self, name_prefix: str | None = None) -> Path | None:
        """Случайный файл из папки (для звуков и шрифтов).

        name_prefix — фильтр по началу имени (например, 'блок' для шрифтов).
        """
        files = self._scan()
        if name_prefix:
            files = [f for f in files
                     if f.name.lower().startswith(name_prefix.lower())]
        if not files:
            return None
        return random.choice(files)

    def mark_consumed(self, path: Path) -> None:
        """Для режима consume: удалить использованный файл из папки."""
        if self.rule.mode != "consume":
            return
        try:
            path.unlink()
            log.info("Материал использован и удалён (consume): %s", path.name)
        except OSError as exc:
            log.error("Не удалось удалить %s: %s", path, exc)


class BackgroundSlicer:
    """Учёт использованных секунд фоновых видео.

    Каждое новое видео берёт следующий отрезок длиной segment_sec из фона.
    Когда фон закончился — переходим к следующему файлу (по правилу папки).
    """

    def __init__(self, pool: AssetPool, state: StateStore, segment_sec: float):
        self.pool = pool
        self.state = state
        self.segment_sec = segment_sec

    def _offset_key(self, filename: str) -> str:
        return f"bg_offset:{filename}"

    def next_segment(self, duration_lookup) -> tuple[Path, float, float] | None:
        """Вернуть (файл, start_sec, length_sec) для следующего видео.

        duration_lookup(path) -> float: длительность файла в секундах
        (обычно через ffprobe; передаётся снаружи, чтобы модуль оставался
        независимым от ffmpeg и легко тестировался).
        """
        bg = self.pool.next()
        if bg is None:
            return None

        total = float(duration_lookup(bg))
        offset = float(self.state.get(self._offset_key(bg.name), 0.0))

        if offset >= total:
            # Фон исчерпан — начинаем сначала (для cycle) либо помечаем расход.
            offset = 0.0

        length = min(self.segment_sec, total - offset)
        self.state.set(self._offset_key(bg.name), offset + length)
        log.debug("Фон %s: отрезок %.2f..%.2f (из %.2f)", bg.name, offset,
                  offset + length, total)
        return bg, offset, length


def build_pools(folders: dict[str, FolderRule], state: StateStore) -> dict[str, AssetPool]:
    return {name: AssetPool(name, rule, state) for name, rule in folders.items()}
