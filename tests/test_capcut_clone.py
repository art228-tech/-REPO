"""Тесты клон-сборки CapCut: подстановка ассетов в эталонный проект."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from autoshorts.config import load_config  # noqa: E402
from autoshorts.montage import capcut_presets as P  # noqa: E402
from autoshorts.montage.capcut_clone import (CloneAssets,  # noqa: E402
                                             _build_word_info, build_clone)
from autoshorts.subtitles import Word  # noqa: E402


def _cfg(tmp_path):
    cfg = load_config(str(Path(__file__).resolve().parents[1] / "config.example.yaml"))
    cfg.montage.setdefault("capcut", {})["drafts_dir"] = str(tmp_path / "drafts")
    return cfg


def test_build_word_info_relative_ms():
    g = [Word("топ", 5.0, 5.4), Word("заняли", 5.4, 6.0)]
    info = _build_word_info(g, 5.0)
    assert info["text"] == "топ заняли"
    real = [w for w in info["info"]["words"] if w["text"] != " "]
    assert real[0]["start_time"] == 0 and real[0]["end_time"] == 400
    assert real[1]["start_time"] == 400 and real[1]["end_time"] == 1000


def test_clone_substitutes_and_keeps_style(tmp_path):
    cfg = _cfg(tmp_path)
    words = [Word("это", 0, 0.4), Word("топ", 0.4, 0.9),
             Word("бравле", 0.9, 1.6), Word("старс", 1.6, 2.2)]
    a = CloneAssets(
        background=Path("bg.mp4"), bg_start=0.0, bg_length=10.0,
        voiceover=Path("vo.mp3"), words=words, emoji=Path("e.png"),
        emoji_anim="zoom1", qr=Path("q.png"), swoosh=Path("sw.mp3"),
        accent_emoji=Path("a1.mp3"), accent_qr=Path("a2.mp3"),
        music=Path("m.mp3"), duration=4.0)
    draft_dir = build_clone(cfg, Path("out/video_0000.mp4"), a, words_per_cue=2)
    data = json.loads((draft_dir / "draft_content.json").read_text(encoding="utf-8"))

    # длительность и канвас
    assert data["duration"] == 4_000_000
    assert data["canvas_config"]["width"] == 1080

    # субтитры: 2 реплики по 2 слова, стиль «Сияние» сохранён
    text_track = [t for t in data["tracks"] if t["type"] == "text"][0]
    assert len(text_track["segments"]) == 2
    tpls = data["materials"]["text_templates"]
    assert all(t["resource_id"] == P.SUBTITLE_TEXT_TEMPLATE_RESOURCE_ID
               for t in tpls)
    texts = {t["id"]: t for t in tpls}
    cue_texts = [texts[s["material_id"]]["current_word_info"]["text"]
                 for s in text_track["segments"]]
    assert cue_texts == ["это топ", "бравле старс"]

    # блюр-эффект сохранён
    assert any(e.get("resource_id") == P.BLUR_EFFECT_RESOURCE_ID
               for e in data["materials"]["video_effects"])

    # озвучка подставлена
    assert any(au.get("path") == "vo.mp3" for au in data["materials"]["audios"])
