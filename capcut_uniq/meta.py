"""Метаданные проекта и регистрация в списке CapCut.

Помимо таймлайна у проекта есть ``draft_meta_info.json`` с абсолютными путями и
общей длительностью, а рядом с папками проектов лежит ``root_meta_info.json`` —
индекс, по которому приложение рисует список. Клон надо прописать и там, иначе
проект может не появиться в интерфейсе.
"""
from __future__ import annotations

import copy
import time
from pathlib import Path

from .draft_io import META_NAME, ROOT_INDEX_NAME, new_draft_id, read_json, write_json_atomic
from .logging_setup import get_logger

log = get_logger("meta")

# Поля облачной привязки: в клоне их надо погасить, иначе CapCut будет считать
# проект копией облачного и может его перезаписать при синхронизации.
CLOUD_FIELDS = (
    "cloud_draft_cover",
    "cloud_package_completed_time",
    "draft_cloud_last_action_download",
    "draft_cloud_template_id",
    "tm_draft_cloud_completed",
    "tm_draft_cloud_entry_id",
    "tm_draft_cloud_modified",
    "tm_draft_cloud_parent_entry_id",
    "tm_draft_cloud_space_id",
    "tm_draft_cloud_user_id",
)


def update_project_meta(
    folder: Path,
    name: str,
    duration_us: int,
    media_replacements: dict[str, tuple[str, str, int]],
) -> str:
    """Правит ``draft_meta_info.json`` клона и возвращает новый идентификатор.

    ``media_replacements`` — отображение старого относительного пути в тройку
    (новый путь, отображаемое имя, длительность в микросекундах).
    """
    path = folder / META_NAME
    if not path.exists():
        log.warning("В клоне нет %s — CapCut может не показать длительность", META_NAME)
        return ""

    meta = read_json(path)
    draft_id = new_draft_id()
    now_us = int(time.time() * 1_000_000)

    meta["draft_id"] = draft_id
    meta["draft_name"] = name
    meta["draft_fold_path"] = str(folder).replace("\\", "/")
    meta["draft_root_path"] = str(folder.parent).replace("\\", "/")
    meta["tm_duration"] = int(duration_us)
    meta["tm_draft_create"] = now_us
    meta["tm_draft_modified"] = now_us
    meta["draft_removable_storage_device"] = ""

    for field in CLOUD_FIELDS:
        if field in meta:
            meta[field] = 0 if isinstance(meta[field], int) else ""
    if isinstance(meta.get("cloud_draft_sync"), dict):
        meta["cloud_draft_sync"] = {}
    meta["draft_is_cloud_temp_draft"] = False

    replaced = 0
    for group in meta.get("draft_materials") or []:
        for item in group.get("value") or []:
            old = item.get("file_Path")
            if old in media_replacements:
                new_path, display_name, duration = media_replacements[old]
                item["file_Path"] = new_path
                item["extra_info"] = display_name
                item["duration"] = int(duration)
                replaced += 1

    write_json_atomic(path, meta)
    log.debug("метаданные обновлены: id=%s, обновлено записей о медиа: %d", draft_id[:8], replaced)
    return draft_id


def register_in_index(
    drafts_dir: Path,
    template_folder: Path,
    new_folder: Path,
    draft_id: str,
    name: str,
    duration_us: int,
) -> bool:
    """Добавляет проект в ``root_meta_info.json``, копируя запись шаблона.

    Индекс недокументирован и в разных сборках выглядит по-разному, поэтому
    работаем осторожно: если разобрать не получилось, просто предупреждаем —
    CapCut во многих версиях подхватывает папку и без записи в индексе.
    """
    index_path = drafts_dir / ROOT_INDEX_NAME
    if not index_path.exists():
        log.debug("Индекс %s отсутствует — пропускаю регистрацию", ROOT_INDEX_NAME)
        return False

    try:
        index = read_json(index_path)
    except ValueError:
        log.warning("Не удалось прочитать %s, регистрация пропущена", ROOT_INDEX_NAME)
        return False

    holder, entries = _find_entries(index)
    if entries is None:
        log.warning("В %s не нашёл список проектов, регистрация пропущена", ROOT_INDEX_NAME)
        return False

    template_path = str(template_folder).replace("\\", "/")
    new_path = str(new_folder).replace("\\", "/")

    source = next((e for e in entries if str(e.get("draft_fold_path", "")).replace("\\", "/") == template_path), None)
    if source is None:
        source = entries[0] if entries else None
    if source is None:
        log.warning("В индексе нет ни одной записи для образца, регистрация пропущена")
        return False

    entry = copy.deepcopy(source)
    now_us = int(time.time() * 1_000_000)
    entry["draft_id"] = draft_id
    entry["draft_name"] = name
    entry["draft_fold_path"] = new_path
    entry["tm_draft_create"] = now_us
    entry["tm_draft_modified"] = now_us
    if "tm_duration" in entry:
        entry["tm_duration"] = int(duration_us)
    if "draft_cover" in entry and isinstance(entry["draft_cover"], str):
        entry["draft_cover"] = f"{new_path}/draft_cover.jpg"

    entries = [e for e in entries if str(e.get("draft_fold_path", "")).replace("\\", "/") != new_path]
    entries.append(entry)
    holder[0][holder[1]] = entries

    write_json_atomic(index_path, index)
    log.debug("проект добавлен в индекс: %s", name)
    return True


def _find_entries(index):
    """Ищет в индексе список записей о проектах."""
    if isinstance(index, dict):
        for key, value in index.items():
            if isinstance(value, list) and value and isinstance(value[0], dict) and "draft_fold_path" in value[0]:
                return (index, key), value
        for key, value in index.items():
            if isinstance(value, list) and not value and "draft" in key.lower():
                return (index, key), value
    return (None, None), None
