"""Ролик без размытого фона: под наложением чёрное поле.

Фон не удаляется, а гасится прозрачностью — тогда сегмент остаётся на месте со
своим звуком и размытием, просто в кадре его не видно, и сквозь него виден
чёрный холст.
"""
from __future__ import annotations

import random
from pathlib import Path

from capcut_uniq import builder, plan as plan_module, profile as profile_module
from capcut_uniq.asr import Transcript, Word
from capcut_uniq.config import Config
from capcut_uniq.draft_io import Draft
from capcut_uniq.ffmpeg import MediaInfo


def words(pairs):
    return [Word(text=text, start=start, end=end) for text, start, end in pairs]


def _prepare(template_folder: Path, black: bool):
    profile = profile_module.analyse(template_folder)
    config = Config(clips_dir=Path("."), voice_dir=Path("."))
    transcript = Transcript(duration=13.0,
                            words=words([("фраза.", 0.0, 2.0), ("вторая", 2.4, 3.0)]))
    line = plan_module.timeline(profile, config, transcript, trailing_silence_s=0.0)
    built = plan_module.build(
        profile, config, line, Path("voice.mp3"),
        [Path("a.mp4"), Path("b.mp4")], [30.0, 30.0], random.Random(1),
    )
    built.black_background = black

    draft = Draft.load(template_folder)
    info = MediaInfo(path=Path("a.mp4"), duration_s=30.0, width=1080, height=1920,
                     has_audio=True, has_video=True, fps=60.0)
    media = {
        f"slot{index}": builder.InstalledMedia(
            material_ids=[], filename="a.mp4", relative="video/a.mp4", info=info)
        for index in range(len(profile.slots))
    }
    builder._apply_slots(draft, profile, built, media, [])
    return draft, profile


def _alphas(draft: Draft, profile):
    background, overlay = [], []
    for slot in profile.slots:
        background.append((slot.background.get(draft).get("clip") or {}).get("alpha"))
        overlay.append((slot.overlay.get(draft).get("clip") or {}).get("alpha"))
    return background, overlay


def test_background_is_hidden_and_overlay_is_not(template_folder: Path):
    draft, profile = _prepare(template_folder, black=True)
    background, overlay = _alphas(draft, profile)

    assert background == [0.0] * len(profile.slots)
    assert all(value != 0.0 for value in overlay)


def test_nothing_is_hidden_by_default(template_folder: Path):
    draft, profile = _prepare(template_folder, black=False)
    background, _ = _alphas(draft, profile)
    assert all(value != 0.0 for value in background)


def test_hidden_background_keeps_its_sound(template_folder: Path):
    """Гасим картинку, а не сегмент: звук клипа должен остаться."""
    draft, profile = _prepare(template_folder, black=True)
    for slot in profile.slots:
        segment = slot.background.get(draft)
        assert segment.get("volume") != 0
        assert segment.get("target_timerange", {}).get("duration", 0) > 0


def test_alpha_keyframes_are_dropped():
    """Ключевой кадр прозрачности перебил бы погашенный фон."""
    segment = {
        "common_keyframes": [
            {"property_type": "KFTypeAlpha", "keyframe_list": [
                {"property_type": "KFTypeAlpha", "value": [1.0]}]},
            {"property_type": "KFTypePositionX", "keyframe_list": [
                {"property_type": "KFTypePositionX", "value": [0.5]}]},
        ]
    }
    builder._drop_alpha_keyframes(segment)

    left = [item["property_type"] for group in segment["common_keyframes"]
            for item in group["keyframe_list"]]
    assert left == ["KFTypePositionX"]


def test_other_keyframes_survive_untouched():
    segment = {"common_keyframes": [
        {"keyframe_list": [{"property_type": "KFTypeScaleX", "value": [1.0]}]}]}
    builder._drop_alpha_keyframes(segment)
    assert len(segment["common_keyframes"]) == 1
