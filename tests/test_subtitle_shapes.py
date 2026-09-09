"""Два устройства текстовых объектов и проверка шаблона на пригодность.

В черновиках с телефона сегмент субтитра ссылается на текстовый шаблон, а тот
уже на текст. После пересохранения десктопным CapCut сегмент нередко ссылается
на текст напрямую. Программа обязана понимать оба варианта: на втором она раньше
не находила дорожку и молча оставляла в ролике текст шаблона.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from capcut_uniq import profile as profile_module, subtitles
from capcut_uniq.config import Config
from capcut_uniq.draft_io import Draft, dumps
from capcut_uniq.errors import PipelineError
from capcut_uniq.plan import Cue

from conftest import make_draft


def _write(folder: Path, draft: dict) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "video").mkdir(exist_ok=True)
    (folder / "audio").mkdir(exist_ok=True)
    payload = dumps(draft)
    (folder / "draft_content.json").write_text(payload, encoding="utf-8")
    return folder


def as_text_shape(draft: dict) -> dict:
    """Переводит дорожку субтитров в вид, который делает десктопный CapCut."""
    templates = {t["id"]: t for t in draft["materials"]["text_templates"]}
    for track in draft["tracks"]:
        if track.get("type") != "sticker":
            continue
        for segment in track["segments"]:
            template = templates.get(segment["material_id"])
            if not template:
                continue
            resource = template["text_info_resources"][0]
            segment["material_id"] = resource["text_material_id"]
            segment["extra_material_refs"] = list(resource.get("extra_material_refs") or [])
        track["type"] = "text"
    draft["materials"]["text_templates"] = []
    return draft


def test_template_shape_detected(template_folder: Path):
    style = profile_module.analyse(template_folder).subtitles
    assert style is not None
    assert style.kind == "template"
    assert style.template_material_id == "TTP0"
    assert style.text_material_id == "TXT0"


def test_text_shape_detected(tmp_path: Path):
    folder = _write(tmp_path / "resaved", as_text_shape(make_draft()))
    profile = profile_module.analyse(folder)

    assert profile.subtitles is not None
    assert profile.subtitles.kind == "text"
    assert profile.subtitle_count == 3
    # Сегмент ссылается на текст напрямую, промежуточного шаблона нет.
    assert profile.subtitles.text_material_id == "TXT0"
    assert profile.subtitles.template_material_id == ""
    assert profile.subtitles.animation_id == "ANI_SUB0"


def test_text_shape_rebuilt(tmp_path: Path):
    folder = _write(tmp_path / "resaved", as_text_shape(make_draft()))
    profile = profile_module.analyse(folder)
    draft = Draft.load(folder)

    cues = [
        Cue("первая реплика", 0, 1_000_000, [("первая", 0, 500), ("реплика", 500, 1000)]),
        Cue("вторая", 1_200_000, 600_000, [("вторая", 0, 600)]),
    ]
    assert subtitles.apply(draft, profile, cues) == 2

    track = draft.tracks[profile.subtitles.track]
    texts = {t["id"]: t for t in draft.materials["texts"]}
    assert len(track["segments"]) == 2
    assert draft.materials["text_templates"] == []
    assert len(texts) == 2

    for position, segment in enumerate(track["segments"]):
        text = texts[segment["material_id"]]
        body = json.loads(text["content"])
        assert body["text"] == cues[position].text
        assert body["styles"][0]["range"] == [0, len(cues[position].text)]
        assert segment["target_timerange"]["duration"] == cues[position].duration_us
        # Анимация подменена на свою, а не оставлена от шаблона.
        assert segment["extra_material_refs"]
        assert "ANI_SUB0" not in segment["extra_material_refs"]


def test_missing_track_with_texts_is_an_error(tmp_path: Path):
    """Текст есть, а дорожку не опознать — партию надо остановить."""
    draft = make_draft()
    for track in draft["tracks"]:
        if track.get("type") == "sticker":
            track["type"] = "какой-то-новый-вид"
    folder = _write(tmp_path / "strange", draft)

    profile = profile_module.analyse(folder)
    assert profile.subtitles is None
    assert profile.subtitle_diagnosis.missing_but_present
    assert not profile.subtitle_diagnosis.absent

    config = Config(clips_dir=tmp_path, voice_dir=tmp_path, templates=[str(folder)])
    with pytest.raises(PipelineError) as info:
        from capcut_uniq import batch

        batch.discover_templates(config)
    assert "не удалось опознать" in str(info.value)


def test_template_without_subtitles_is_allowed(tmp_path: Path):
    """Субтитров не было изначально — это нормально, работать можно."""
    draft = make_draft()
    draft["tracks"] = [t for t in draft["tracks"] if t.get("type") != "sticker"]
    draft["materials"]["texts"] = []
    draft["materials"]["text_templates"] = []
    folder = _write(tmp_path / "no-subs", draft)

    profile = profile_module.analyse(folder)
    assert profile.subtitles is None
    assert profile.subtitle_diagnosis.absent
    assert not profile.subtitle_diagnosis.missing_but_present

    config = Config(clips_dir=tmp_path, voice_dir=tmp_path, templates=[str(folder)])
    from capcut_uniq import batch

    # Не должно бросить исключение: такой шаблон допустим.
    assert len(batch.discover_templates(config)) == 1


def test_apply_on_missing_style_does_nothing(tmp_path: Path):
    draft_data = make_draft()
    draft_data["tracks"] = [t for t in draft_data["tracks"] if t.get("type") != "sticker"]
    draft_data["materials"]["texts"] = []
    draft_data["materials"]["text_templates"] = []
    folder = _write(tmp_path / "no-subs", draft_data)

    profile = profile_module.analyse(folder)
    draft = Draft.load(folder)
    assert subtitles.apply(draft, profile, [Cue("текст", 0, 1000, [("текст", 0, 1000)])]) == 0
