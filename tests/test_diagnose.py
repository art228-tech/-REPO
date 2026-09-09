"""Диагностика субтитров.

Смысл её в том, чтобы поломку было видно в журнале, а не только на экране
CapCut. Субтитр может лежать в черновике безупречно с точки зрения ссылок и
таймингов и всё равно не отрисоваться, если какое-то поле отличается от того,
что кладёт само приложение.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from capcut_uniq import diagnose
from capcut_uniq.draft_io import Draft, dumps

from conftest import make_draft


def _project(folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "video").mkdir(exist_ok=True)
    (folder / "audio").mkdir(exist_ok=True)
    (folder / "draft_content.json").write_text(dumps(make_draft()), encoding="utf-8")
    return folder


def test_healthy_clone_has_no_problems(tmp_path: Path):
    template = _project(tmp_path / "template")
    clone = tmp_path / "clone"
    shutil.copytree(template, clone)

    report = diagnose.compare(template, clone)
    assert not report.problems, report.describe()


def test_catches_words_past_the_cue_edge(tmp_path: Path):
    template = _project(tmp_path / "template")
    clone = _project(tmp_path / "clone")

    draft = Draft.load(clone)
    draft.materials["texts"][0]["words"] = {
        "start_time": [0], "end_time": [9_000], "text": ["слово"],
    }
    draft.save()

    report = diagnose.compare(template, clone)
    assert any("слова кончаются" in item.text for item in report.problems)


def test_catches_reversed_word_order(tmp_path: Path):
    template = _project(tmp_path / "template")
    clone = _project(tmp_path / "clone")

    draft = Draft.load(clone)
    draft.materials["texts"][0]["words"] = {
        "start_time": [500, 100], "end_time": [700, 1_500], "text": ["раз", "два"],
    }
    draft.save()

    report = diagnose.compare(template, clone)
    assert any("не по возрастанию" in item.text for item in report.problems)


def test_catches_style_range_mismatch(tmp_path: Path):
    template = _project(tmp_path / "template")
    clone = _project(tmp_path / "clone")

    draft = Draft.load(clone)
    text = draft.materials["texts"][0]
    body = json.loads(text["content"])
    body["styles"][0]["range"] = [0, 999]
    text["content"] = json.dumps(body, ensure_ascii=False)
    draft.save()

    report = diagnose.compare(template, clone)
    assert any("диапазон оформления" in item.text for item in report.problems)


def test_catches_animation_length_mismatch(tmp_path: Path):
    template = _project(tmp_path / "template")
    clone = _project(tmp_path / "clone")

    draft = Draft.load(clone)
    for animation in draft.materials["material_animations"]:
        for item in animation.get("animations") or []:
            if item.get("type") == "caption":
                item["duration"] = 50_000
    draft.save()

    report = diagnose.compare(template, clone)
    assert any("анимация" in item.text for item in report.problems)


def test_catches_unexpected_field_change(tmp_path: Path):
    """Любое неожиданное расхождение с шаблоном должно попасть в отчёт."""
    template = _project(tmp_path / "template")
    clone = _project(tmp_path / "clone")

    draft = Draft.load(clone)
    draft.materials["texts"][0]["text_color"] = "#00FF00FF"
    draft.save()

    report = diagnose.compare(template, clone)
    assert any("text_color" in item.text for item in report.problems)


def test_animation_duration_is_not_reported_as_field_diff(tmp_path: Path):
    """Длительность анимации обязана отличаться — это не расхождение."""
    template = _project(tmp_path / "template")
    clone = _project(tmp_path / "clone")

    draft = Draft.load(clone)
    for animation in draft.materials["material_animations"]:
        for item in animation.get("animations") or []:
            if item.get("type") == "caption":
                item["duration"] = 1_500_000
    draft.save()

    report = diagnose.compare(template, clone)
    assert not any("поле animations отличается" in item.text for item in report.problems)


def test_bundle_is_written_and_readable(tmp_path: Path):
    template = _project(tmp_path / "template")
    clone = tmp_path / "clone"
    shutil.copytree(template, clone)

    report = diagnose.compare(template, clone)
    path = diagnose.write_bundle(report, tmp_path / "logs")

    assert path.exists()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["шаблон"]["имя"] == "template"
    assert payload["ролик"]["имя"] == "clone"
    # В слепке лежат настоящие объекты, а не только текст отчёта.
    assert payload["ролик"]["субтитры"][0]["текст"]["content"]
    assert payload["ролик"]["субтитры"][0]["сегмент"]["target_timerange"]
