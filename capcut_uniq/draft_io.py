"""Чтение и запись черновиков CapCut.

Проверено на реальных проектах: если писать компактным JSON без экранирования
не-ASCII, файл побайтово совпадает с тем, что пишет само приложение.

В папке проекта таймлайн лежит сразу в нескольких файлах. Живых два —
``draft_content.json`` и зеркало ``template-2.tmp``; приложение читает зеркало
приоритетно, поэтому писать нужно в оба. Файлы ``*.bak`` — это резервные копии,
которые CapCut пересоздаёт сам при открытии проекта; в клоне их нужно удалить,
иначе в них останется исходное содержимое шаблона.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import uuid
from pathlib import Path
from typing import Any, Iterable

from .errors import TemplateError
from .logging_setup import get_logger

log = get_logger("draft")

CONTENT_NAME = "draft_content.json"
MIRROR_NAMES = ("template-2.tmp",)
STALE_NAMES = ("draft_content.json.bak", "template.json.bak")
META_NAME = "draft_meta_info.json"
ROOT_INDEX_NAME = "root_meta_info.json"

PLACEHOLDER_TEMPLATE = "##_draftpath_placeholder_{guid}_##"
PLACEHOLDER_RE = re.compile(r"^##_draftpath_placeholder_([0-9A-Fa-f-]+)_##")


def dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def read_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json_atomic(path: Path, data: Any) -> None:
    """Пишет через временный файл и переименование, чтобы не оставить обрубок."""
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp_write")
    tmp.write_text(dumps(data), encoding="utf-8", newline="")
    os.replace(tmp, path)


def new_capcut_id() -> str:
    """Идентификатор в стиле CapCut: 8-4-4-4-12 заглавными, без дефисной группы UUID."""
    raw = uuid.uuid4().hex.upper()
    return f"{raw[:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:32]}"


def new_draft_id() -> str:
    return uuid.uuid4().hex


class Draft:
    """Черновик проекта: сам JSON таймлайна и папка со всеми файлами."""

    def __init__(self, folder: Path, content: dict):
        self.folder = Path(folder)
        self.content = content

    # --- загрузка и сохранение -------------------------------------------------

    @classmethod
    def load(cls, folder: Path) -> "Draft":
        folder = Path(folder)
        path = folder / CONTENT_NAME
        if not path.exists():
            raise TemplateError(f"В папке {folder.name} нет файла {CONTENT_NAME}")
        raw = path.read_text(encoding="utf-8")
        if not raw.lstrip().startswith("{"):
            raise TemplateError(
                f"{folder.name}: {CONTENT_NAME} не является текстовым JSON. "
                "Похоже, версия CapCut шифрует черновики — такая не подходит."
            )
        return cls(folder, json.loads(raw))

    def save(self) -> list[Path]:
        """Записывает таймлайн во все живые файлы и убирает устаревшие копии."""
        written: list[Path] = []
        payload = dumps(self.content)

        for name in (CONTENT_NAME, *MIRROR_NAMES):
            target = self.folder / name
            tmp = target.with_suffix(target.suffix + ".tmp_write")
            tmp.write_text(payload, encoding="utf-8", newline="")
            os.replace(tmp, target)
            written.append(target)

        for name in STALE_NAMES:
            stale = self.folder / name
            if stale.exists():
                stale.unlink()
                log.debug("удалена устаревшая копия %s", name)

        log.debug("записан таймлайн: %s", ", ".join(p.name for p in written))
        return written

    # --- доступ к содержимому --------------------------------------------------

    @property
    def duration_us(self) -> int:
        return int(self.content.get("duration") or 0)

    @duration_us.setter
    def duration_us(self, value: int) -> None:
        self.content["duration"] = int(value)

    @property
    def tracks(self) -> list[dict]:
        return self.content.setdefault("tracks", [])

    @property
    def materials(self) -> dict:
        return self.content.setdefault("materials", {})

    def material_index(self) -> dict[str, tuple[str, dict]]:
        """Отображение идентификатора материала в пару (раздел, объект)."""
        index: dict[str, tuple[str, dict]] = {}
        for section, items in self.materials.items():
            if not isinstance(items, list):
                continue
            for item in items:
                if isinstance(item, dict) and item.get("id"):
                    index[item["id"]] = (section, item)
        return index

    def find_material(self, material_id: str) -> dict | None:
        found = self.material_index().get(material_id)
        return found[1] if found else None

    def placeholder_guid(self) -> str | None:
        """GUID, которым CapCut подменяет путь к папке проекта в ссылках на медиа."""
        for section in ("videos", "audios"):
            for item in self.materials.get(section, []) or []:
                match = PLACEHOLDER_RE.match(item.get("path") or "")
                if match:
                    return match.group(1)
        return None

    def relative_media_path(self, subdir: str, filename: str) -> str:
        guid = self.placeholder_guid()
        if not guid:
            # Шаблон без плейсхолдера — используем абсолютный путь.
            return str(self.folder / subdir / filename).replace("\\", "/")
        return f"{PLACEHOLDER_TEMPLATE.format(guid=guid)}/{subdir}/{filename}"


def clone_folder(source: Path, target: Path, skip_files: Iterable[Path] = ()) -> None:
    """Копирует папку проекта, пропуская заданные файлы.

    Пропуск нужен, чтобы не тащить исходник геймплея: в шаблонах он занимает
    почти 500 МБ, а в собранном ролике всё равно заменяется на новый клип.
    """
    source = Path(source)
    target = Path(target)
    skip = {Path(p).resolve() for p in skip_files}

    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)

    copied = 0
    skipped = 0
    for item in source.rglob("*"):
        relative = item.relative_to(source)
        destination = target / relative
        if item.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
            continue
        if item.resolve() in skip or item.name in STALE_NAMES:
            skipped += 1
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, destination)
        copied += 1

    log.debug("клон %s → %s: скопировано %d, пропущено %d", source.name, target.name, copied, skipped)
