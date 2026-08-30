"""Чтение и запись черновика, клонирование папки, самопроверка."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from capcut_uniq import validate
from capcut_uniq.draft_io import Draft, clone_folder, dumps, new_capcut_id
from capcut_uniq.errors import TemplateError


def test_compact_json_matches_capcut(template_folder: Path):
    """CapCut пишет JSON без пробелов — при таком же формате файл совпадает побайтово."""
    raw = (template_folder / "draft_content.json").read_text(encoding="utf-8")
    assert dumps(json.loads(raw)) == raw


def test_save_writes_mirror_and_drops_stale(template_folder: Path):
    draft = Draft.load(template_folder)
    draft.content["name"] = "изменено"
    draft.save()

    content = json.loads((template_folder / "draft_content.json").read_text(encoding="utf-8"))
    mirror = json.loads((template_folder / "template-2.tmp").read_text(encoding="utf-8"))

    assert content["name"] == "изменено"
    assert mirror == content
    assert not (template_folder / "draft_content.json.bak").exists()


def test_encrypted_draft_reports_clearly(tmp_path: Path):
    folder = tmp_path / "encrypted"
    folder.mkdir()
    (folder / "draft_content.json").write_bytes(b"\x8a\x01\x02\x03binary")

    with pytest.raises(TemplateError) as info:
        Draft.load(folder)
    assert "шифрует" in str(info.value)


def test_placeholder_guid_parsed(template_folder: Path):
    draft = Draft.load(template_folder)
    assert draft.placeholder_guid() == "0E685133-18CE-45ED-8CB8-2904A212EC80"
    assert draft.relative_media_path("video", "new.mp4").endswith("_##/video/new.mp4")


def test_clone_skips_requested_files(template_folder: Path, tmp_path: Path):
    heavy = template_folder / "video" / "gameplay.mp4"
    target = tmp_path / "clone"

    clone_folder(template_folder, target, skip_files=[heavy])

    assert (target / "draft_content.json").exists()
    assert (target / "video" / "emoji.mp4").exists()
    assert not (target / "video" / "gameplay.mp4").exists()
    assert not (target / "draft_content.json.bak").exists()


def test_new_id_shape():
    value = new_capcut_id()
    assert len(value) == 36
    assert [len(part) for part in value.split("-")] == [8, 4, 4, 4, 12]
    assert value.upper() == value


def test_validator_accepts_template(template_folder: Path):
    report = validate.check(template_folder)
    assert report.ok, report.describe()


def test_validator_catches_dangling_reference(template_folder: Path):
    draft = Draft.load(template_folder)
    draft.tracks[0]["segments"][0]["material_id"] = "НЕТ-ТАКОГО"
    draft.save()

    report = validate.check(template_folder)
    assert not report.ok
    assert any("несуществующий материал" in item for item in report.errors)


def test_validator_catches_overlap(template_folder: Path):
    draft = Draft.load(template_folder)
    segments = draft.tracks[0]["segments"]
    segments[1]["target_timerange"]["start"] = 100_000
    draft.save()

    report = validate.check(template_folder)
    assert not report.ok
    assert any("наезжает" in item for item in report.errors)


def test_validator_catches_keyframe_drift(template_folder: Path):
    draft = Draft.load(template_folder)
    for track in draft.tracks:
        for segment in track["segments"]:
            if segment.get("common_keyframes"):
                segment["clip"]["transform"]["y"] = 0.9
    draft.save()

    report = validate.check(template_folder)
    assert not report.ok
    assert any("кейфрейм" in item.lower() for item in report.errors)


def test_validator_catches_missing_media(template_folder: Path):
    (template_folder / "video" / "emoji.mp4").unlink()

    report = validate.check(template_folder)
    assert not report.ok
    assert any("нет файла" in item for item in report.errors)
