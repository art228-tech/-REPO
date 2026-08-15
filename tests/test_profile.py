"""Разбор шаблона: роли дорожек находятся по признакам, а не по номерам."""
from __future__ import annotations

import json
from pathlib import Path

from capcut_uniq import profile as profile_module
from capcut_uniq.units import us2s

from conftest import make_draft


def test_roles_detected(template_folder: Path):
    profile = profile_module.analyse(template_folder)

    assert profile.total_us == 12_800_000
    assert profile.width == 1080 and profile.height == 1920
    assert profile.cut_us == 2_400_000
    assert len(profile.slots) == 2

    # Фон и наложение указывают на разные дорожки, но на одинаковые тайминги.
    assert profile.slots[0].background.track != profile.slots[0].overlay.track
    assert profile.slots[0].duration_us == 2_400_000
    assert profile.slots[1].duration_us == 10_400_000
    assert round(profile.slots[0].background_scale, 2) == 4.0
    assert round(profile.slots[0].overlay_scale, 2) == 2.67


def test_anchors_measured(template_folder: Path):
    profile = profile_module.analyse(template_folder)

    assert profile.swoosh is not None
    assert profile.swoosh_offset_us == -190_000
    assert profile.tail_after_voice_us == 12_800_000 - (7000 + 12_700_000)

    assert profile.sticker is not None
    assert profile.sticker.speed == 1.3
    assert profile.sticker.source_duration_us == 3_000_000
    assert profile.sticker.sfx is not None
    assert profile.sticker.sfx_offset_us == 5_690_000 - 5_667_000
    assert profile.sticker.sfx_volume == 0.40

    assert profile.qr is not None
    assert profile.qr.duration_us == 1_100_000
    assert profile.qr.sfx is not None
    assert profile.qr.sfx_offset_us == 0


def test_music_optional(tmp_path: Path):
    """У одного из реальных шаблонов нет музыки — нумерация дорожек съезжает."""
    folder = tmp_path / "no-music"
    (folder / "video").mkdir(parents=True)
    (folder / "audio").mkdir(parents=True)
    payload = json.dumps(make_draft(with_music=False), ensure_ascii=False, separators=(",", ":"))
    (folder / "draft_content.json").write_text(payload, encoding="utf-8")

    profile = profile_module.analyse(folder)
    assert profile.music is None
    assert profile.sticker is not None
    assert profile.qr is not None
    assert profile.subtitles is not None


def test_subtitle_style_captured(template_folder: Path):
    profile = profile_module.analyse(template_folder)
    style = profile.subtitles

    assert style is not None
    assert profile.subtitle_count == 3
    assert style.template_material_id == "TTP0"
    assert style.text_material_id == "TXT0"
    assert style.animation_id == "ANI_SUB0"
    assert round(style.offset_y, 2) == -0.51
    assert len(style.metrics) == 3
