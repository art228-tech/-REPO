"""Клонирование проекта: переносим только необходимое.

Служебные файлы, которые десктопный CapCut создаёт при открытии, содержат ссылки
на прежний проект. Если тащить их в клон, приложение находит там другой таймлайн
и открывает пустой — собранный ролик выглядит как чёрный экран.
"""
from __future__ import annotations

import json
from pathlib import Path

from capcut_uniq.draft_io import KEEP_DIRS, KEEP_FILES, Draft, clone_folder


def _messy_template(folder: Path) -> Path:
    """Шаблон в том виде, в каком он остаётся после работы в CapCut."""
    (folder / "video").mkdir(parents=True)
    (folder / "audio").mkdir(parents=True)
    (folder / "common_attachment").mkdir(parents=True)

    (folder / "draft_content.json").write_text('{"id":"СТАРЫЙ-ТАЙМЛАЙН","tracks":[]}', encoding="utf-8")
    (folder / "template-2.tmp").write_text('{"id":"СТАРЫЙ-ТАЙМЛАЙН","tracks":[]}', encoding="utf-8")
    (folder / "draft_meta_info.json").write_text('{"draft_id":"старый"}', encoding="utf-8")
    for name in ("draft.extra", "draft_settings", "template.tmp", "cover.png"):
        (folder / name).write_bytes(b"x" * 16)

    # Вот это и есть источник беды: файлы со ссылками на прежний таймлайн.
    (folder / "timeline_layout.json").write_text('{"timeline":"СТАРЫЙ-ТАЙМЛАЙН"}', encoding="utf-8")
    (folder / "attachment_pc_common.json").write_text('{"timeline":"СТАРЫЙ-ТАЙМЛАЙН"}', encoding="utf-8")
    (folder / "key_value.json").write_text("{}", encoding="utf-8")
    (folder / "performance_opt_info.json").write_text("{}", encoding="utf-8")
    (folder / "draft_content.json.bak").write_text("{}", encoding="utf-8")
    (folder / "template.json.bak").write_text("{}", encoding="utf-8")
    (folder / "draft_cover.jpg").write_bytes(b"x" * 16)
    (folder / "common_attachment" / "attachment_clipflow_cache.json").write_text("{}", encoding="utf-8")

    (folder / "video" / "gameplay.mp4").write_bytes(b"y" * 64)
    (folder / "video" / "emoji.mp4").write_bytes(b"y" * 32)
    (folder / "audio" / "voice.mp3").write_bytes(b"z" * 32)
    return folder


def test_only_needed_files_travel(tmp_path: Path):
    source = _messy_template(tmp_path / "template")
    target = tmp_path / "clone"

    clone_folder(source, target)

    survived = {item.name for item in target.iterdir() if item.is_file()}
    assert survived <= set(KEEP_FILES)
    assert "draft_content.json" in survived
    assert "draft_meta_info.json" in survived

    # Ровно те файлы, из-за которых появлялся пустой таймлайн.
    for name in ("timeline_layout.json", "attachment_pc_common.json",
                 "key_value.json", "performance_opt_info.json", "draft_cover.jpg"):
        assert not (target / name).exists(), name

    # Резервные копии тоже не нужны: в них лежит исходное содержимое шаблона.
    assert not (target / "draft_content.json.bak").exists()
    assert not (target / "template.json.bak").exists()
    assert not (target / "common_attachment").exists()


def test_media_folders_travel(tmp_path: Path):
    source = _messy_template(tmp_path / "template")
    target = tmp_path / "clone"

    clone_folder(source, target)

    assert (target / "video" / "gameplay.mp4").exists()
    assert (target / "video" / "emoji.mp4").exists()
    assert (target / "audio" / "voice.mp3").exists()
    for name in KEEP_DIRS:
        assert (target / name).is_dir()


def test_heavy_media_can_be_skipped(tmp_path: Path):
    """Исходник геймплея не переносится: он всё равно заменяется клипом."""
    source = _messy_template(tmp_path / "template")
    target = tmp_path / "clone"

    clone_folder(source, target, skip_files=[source / "video" / "gameplay.mp4"])

    assert not (target / "video" / "gameplay.mp4").exists()
    assert (target / "video" / "emoji.mp4").exists()


def test_timeline_id_is_not_touched(tmp_path: Path):
    """Идентификатор таймлайна должен остаться прежним.

    Раньше здесь выдавался новый, и любой уцелевший служебный файл со старым
    заставлял CapCut открыть пустой таймлайн вместо собранного.
    """
    source = _messy_template(tmp_path / "template")
    target = tmp_path / "clone"
    clone_folder(source, target)

    original = json.loads((source / "draft_content.json").read_text(encoding="utf-8"))["id"]
    clone = Draft.load(target)
    assert clone.content["id"] == original
