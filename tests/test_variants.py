"""Перебор способов записать субтитры.

CapCut не объясняет, почему не рисует текст, поэтому один ролик собирается
несколькими способами. Здесь проверяется, что способы действительно различаются
тем, чем должны, — иначе перебор ничего не покажет.
"""
from __future__ import annotations

import json
from pathlib import Path

from capcut_uniq import profile as profile_module, subtitles, variants
from capcut_uniq.draft_io import Draft, dumps
from capcut_uniq.plan import Cue

from conftest import make_draft


def _draft(tmp_path: Path) -> tuple[Draft, object]:
    folder = tmp_path / "проект"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "video").mkdir(exist_ok=True)
    (folder / "audio").mkdir(exist_ok=True)
    (folder / "draft_content.json").write_text(dumps(make_draft()), encoding="utf-8")
    return Draft.load(folder), profile_module.analyse(folder)


CUES = [
    Cue(text="первая реплика", start_us=0, duration_us=1_000_000,
        words=[("первая", 0, 500), ("реплика", 500, 1000)]),
    Cue(text="вторая реплика", start_us=1_200_000, duration_us=1_000_000,
        words=[("вторая", 0, 500), ("реплика", 500, 1000)]),
]


def _chain(draft: Draft, style):
    """Первый субтитр: сегмент, оформление и текст."""
    index = draft.material_index()
    segment = draft.tracks[style.track]["segments"][0]
    kind, material = index[segment["material_id"]]
    if kind == "text_templates":
        text_id = material["text_info_resources"][0]["text_material_id"]
    else:
        text_id = segment["material_id"]
    text = next(t for t in draft.materials["texts"] if t["id"] == text_id)
    return segment, kind, text


def test_every_way_has_its_own_name():
    names = [way.name for way in variants.WAYS]
    assert len(names) == len(set(names))
    assert variants.CONTROL not in names


def test_default_way_uses_the_text_template(tmp_path: Path):
    draft, profile = _draft(tmp_path)
    subtitles.apply(draft, profile, CUES)
    _, kind, _ = _chain(draft, profile.subtitles)
    assert kind == "text_templates"


def test_plain_text_way_drops_the_text_template(tmp_path: Path):
    draft, profile = _draft(tmp_path)
    subtitles.apply(draft, profile, CUES, subtitles.Way(device="text"))
    segment, kind, text = _chain(draft, profile.subtitles)
    assert kind == "texts"
    assert segment["material_id"] == text["id"]


def test_capcut_style_ids_are_not_plain_uuids(tmp_path: Path):
    draft, profile = _draft(tmp_path)
    subtitles.apply(draft, profile, CUES, subtitles.Way(ids="capcut"))
    segment, _, _ = _chain(draft, profile.subtitles)
    parts = segment["material_id"].split("-")
    assert [len(p) for p in parts] == [8, 4, 4, 4, 12]
    assert segment["material_id"] == segment["material_id"].upper()


def test_borrowed_ids_are_occupied(tmp_path: Path):
    draft, profile = _draft(tmp_path)
    borrow = subtitles.original_ids(draft, profile.subtitles.track)
    wanted = borrow[0]["template"]

    subtitles.apply(draft, profile, CUES, subtitles.Way(ids="template"), borrow=borrow)
    segment, _, _ = _chain(draft, profile.subtitles)
    assert segment["material_id"] == wanted


def test_borrowed_words_are_kept_verbatim(tmp_path: Path):
    draft, profile = _draft(tmp_path)
    borrow = subtitles.original_ids(draft, profile.subtitles.track)
    wanted = borrow[0].get("words")

    subtitles.apply(draft, profile, CUES, subtitles.Way(words="template"), borrow=borrow)
    _, _, text = _chain(draft, profile.subtitles)
    assert text["words"] == wanted


def test_empty_words_way_leaves_no_word_split(tmp_path: Path):
    draft, profile = _draft(tmp_path)
    subtitles.apply(draft, profile, CUES, subtitles.Way(words="empty"))
    _, _, text = _chain(draft, profile.subtitles)
    assert text["words"]["text"] == []


def test_way_without_animation_leaves_no_reference(tmp_path: Path):
    draft, profile = _draft(tmp_path)
    subtitles.apply(draft, profile, CUES, subtitles.Way(animation=False))
    segment, _, _ = _chain(draft, profile.subtitles)
    animations = {a["id"] for a in draft.materials["material_animations"]}
    assert not [r for r in segment.get("extra_material_refs") or [] if r in animations]


def test_text_still_lands_whatever_the_way(tmp_path: Path):
    """Текст реплики должен доезжать при любом способе."""
    for way in variants.WAYS:
        draft, profile = _draft(tmp_path / way.name)
        subtitles.apply(draft, profile, CUES, way)
        _, _, text = _chain(draft, profile.subtitles)
        assert json.loads(text["content"])["text"] == CUES[0].text, way.name
