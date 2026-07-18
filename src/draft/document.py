"""Загрузка/сохранение и низкоуровневые операции над draft_content.json CapCut."""

from __future__ import annotations

import copy
import json
import uuid
from pathlib import Path
from typing import Any

from ..logging_setup import get_logger

logger = get_logger()


def new_id() -> str:
    """CapCut использует UPPERCASE UUID для id материалов/сегментов."""
    return str(uuid.uuid4()).upper()


class DraftDocument:
    """Обёртка над содержимым draft_content.json."""

    def __init__(self, data: dict[str, Any], path: Path | None = None) -> None:
        self.data = data
        self.path = path
        self._rebuild_index()

    # ---- загрузка/сохранение ----

    @classmethod
    def load(cls, path: str | Path) -> "DraftDocument":
        path = Path(path)
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(data, path)

    def save(self, path: str | Path | None = None, backup: bool = True) -> Path:
        target = Path(path) if path else self.path
        if target is None:
            raise ValueError("Не задан путь для сохранения draft")
        if backup and target.exists():
            bak = target.with_suffix(target.suffix + ".bak")
            try:
                bak.write_bytes(target.read_bytes())
            except OSError as e:  # noqa: BLE001
                logger.warning("Не удалось создать резервную копию %s: %s", bak, e)
        # CapCut хранит JSON компактно, без пробелов между разделителями.
        target.write_text(
            json.dumps(self.data, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        return target

    # ---- индекс материалов ----

    def _rebuild_index(self) -> None:
        self._index: dict[str, tuple[str, dict]] = {}
        for category, arr in self.materials.items():
            if isinstance(arr, list):
                for obj in arr:
                    if isinstance(obj, dict) and "id" in obj:
                        self._index[obj["id"]] = (category, obj)

    @property
    def materials(self) -> dict[str, Any]:
        return self.data.setdefault("materials", {})

    @property
    def tracks(self) -> list[dict]:
        return self.data.setdefault("tracks", [])

    @property
    def total_duration(self) -> int:
        return int(self.data.get("duration", 0))

    @total_duration.setter
    def total_duration(self, value: int) -> None:
        self.data["duration"] = int(value)

    def material(self, material_id: str) -> tuple[str, dict] | None:
        return self._index.get(material_id)

    def material_obj(self, material_id: str) -> dict | None:
        found = self._index.get(material_id)
        return found[1] if found else None

    # ---- добавление материалов (клонированием существующего того же типа) ----

    def clone_material_from(self, template_id: str, overrides: dict[str, Any]) -> str:
        """Клонирует материал с id=template_id, применяет overrides, добавляет
        в ту же категорию и возвращает новый id."""
        found = self.material(template_id)
        if not found:
            raise KeyError(f"Материал-шаблон не найден: {template_id}")
        category, template = found
        clone = copy.deepcopy(template)
        clone["id"] = new_id()
        clone.update(overrides)
        self.materials[category].append(clone)
        self._index[clone["id"]] = (category, clone)
        return clone["id"]

    def add_material(self, category: str, obj: dict[str, Any]) -> str:
        obj.setdefault("id", new_id())
        self.materials.setdefault(category, []).append(obj)
        self._index[obj["id"]] = (category, obj)
        return obj["id"]

    def remove_material(self, material_id: str) -> None:
        found = self._index.pop(material_id, None)
        if not found:
            return
        category, obj = found
        arr = self.materials.get(category, [])
        if obj in arr:
            arr.remove(obj)
