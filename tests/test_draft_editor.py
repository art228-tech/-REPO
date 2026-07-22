"""Тесты ядра правки проекта: распознавание таймлайна, синхронизация конца,
перестановка наложения и — главное — позиция/масштаб субтитров (то, чего
раньше не было). Работают без CapCut и без GUI (чистый Python).

Структура синтетического проекта повторяет реальный draft пользователя
(CapCut 9.0, 9:16): 3 видео-дорожки, 3 аудио-дорожки, 1 текст-дорожка с
субтитрами на шаблоне (material_id сегмента = text_template).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.draft.document import DraftDocument
from src.draft.editor import DraftEditor


US = 1_000_000


def _tr(start, dur):
    return {"start": int(start), "duration": int(dur)}


def _seg(mid, start, dur, *, volume=1.0, extra=None, clip=None, speed=1.0):
    return {
        "id": mid + "_SEG",
        "material_id": mid,
        "target_timerange": _tr(start, dur),
        "source_timerange": _tr(0, dur),
        "volume": volume,
        "speed": speed,
        "extra_material_refs": extra or [],
        "clip": clip or {},
    }


def make_sample_draft() -> dict:
    """Минимальный, но валидный по структуре проект (12 c)."""
    total = 12 * US
    intro = int(2.17 * US)

    materials = {
        "videos": [
            {"id": "VID_BLUR_INTRO", "type": "video", "duration": 30 * US},
            {"id": "VID_BLUR_MAIN", "type": "video", "duration": 30 * US},
            {"id": "VID_FG_INTRO", "type": "video", "duration": 30 * US},
            {"id": "VID_FG_MAIN", "type": "video", "duration": 30 * US},
            {"id": "VID_OVERLAY", "type": "video", "duration": 5 * US},
            {"id": "PHOTO_END", "type": "photo", "duration": 5 * US},
        ],
        "audios": [
            {"id": "AUD_VOICE", "type": "extract_music", "duration": 30 * US},
            {"id": "AUD_SFX_TRANS", "type": "music", "duration": 2 * US},
            {"id": "AUD_SFX_PREOV", "type": "music", "duration": 2 * US},
            {"id": "AUD_SFX_PREPH", "type": "music", "duration": 2 * US},
            {"id": "AUD_BG", "type": "music", "duration": 30 * US},
        ],
        "video_effects": [{"id": "FX_BLUR", "type": "video_effect", "name": "Размытие"}],
        "texts": [
            {
                "id": "TXT1", "type": "subtitle", "content": "{\"text\":\"привет\"}",
                "font_name": "", "font_id": "", "font_resource_id": "7579481374890003713",
                "style_name": "", "text_color": "#ffffff", "border_alpha": 0.0,
            },
            {"id": "TXT2", "type": "subtitle", "content": "{\"text\":\"мир\"}",
             "font_resource_id": "7579481374890003713"},
        ],
        "text_templates": [
            {"id": "3B4F9BD6-TMPL", "type": "text_template_subtitle",
             "effect_id": "7577568565935475985", "resource_id": "7577568565935475985",
             "name": "cc_template"},
            {"id": "9EC2CC79-TMPL", "type": "text_template_subtitle",
             "effect_id": "7577568565935475985", "resource_id": "7577568565935475985",
             "name": "cc_template"},
        ],
    }

    clip_sub = {"scale": {"x": 1.14, "y": 1.14}, "transform": {"x": 0.0, "y": -0.475}}

    tracks = [
        # размытый фон (с эффектом)
        {"type": "video", "segments": [
            _seg("VID_BLUR_INTRO", 0, intro, extra=["FX_BLUR"],
                 clip={"scale": {"x": 1.3, "y": 1.3}}),
            _seg("VID_BLUR_MAIN", intro, total - intro, extra=["FX_BLUR"],
                 clip={"scale": {"x": 1.3, "y": 1.3}}),
        ]},
        # передний фон
        {"type": "video", "segments": [
            _seg("VID_FG_INTRO", 0, intro, clip={"scale": {"x": 1.0, "y": 1.0}}),
            _seg("VID_FG_MAIN", intro, total - intro, clip={"scale": {"x": 1.0, "y": 1.0}}),
        ]},
        # наложение + фото
        {"type": "video", "segments": [
            _seg("VID_OVERLAY", int(5.33 * US), int(2.23 * US)),
            _seg("PHOTO_END", int(11.1 * US), int(0.9 * US)),
        ]},
        # текст (субтитры на шаблоне)
        {"type": "text", "segments": [
            _seg("3B4F9BD6-TMPL", 0, int(2.23 * US), extra=["TXT1"], clip=dict(clip_sub)),
            _seg("9EC2CC79-TMPL", int(2.4 * US), int(2.4 * US), extra=["TXT2"],
                 clip={"scale": {"x": 1.14, "y": 1.14}, "transform": {"x": 0.0, "y": -0.475}}),
        ]},
        # озвучка (громкая, весь ролик)
        {"type": "audio", "segments": [_seg("AUD_VOICE", 0, total, volume=1.0)]},
        # звуки (3 сегмента)
        {"type": "audio", "segments": [
            _seg("AUD_SFX_TRANS", int(2.07 * US), int(0.43 * US), volume=0.13),
            _seg("AUD_SFX_PREOV", int(5.33 * US), int(1.97 * US), volume=1.0),
            _seg("AUD_SFX_PREPH", int(11.13 * US), int(0.97 * US), volume=0.25),
        ]},
        # фоновая музыка (тихая, весь ролик)
        {"type": "audio", "segments": [_seg("AUD_BG", 0, total, volume=0.05)]},
    ]

    return {"duration": total, "fps": 30.0, "materials": materials, "tracks": tracks}


def _editor() -> DraftEditor:
    return DraftEditor(DraftDocument(make_sample_draft()))


def test_layout_detection():
    ed = _editor()
    lay = ed.layout
    assert len(lay.sfx_segments) == 3
    # озвучка громче фоновой музыки
    assert lay.voiceover_segment["material_id"] == "AUD_VOICE"
    assert lay.bgmusic_segment["material_id"] == "AUD_BG"
    # фото распознано на дорожке наложения
    assert lay.photo_segment["material_id"] == "PHOTO_END"
    assert lay.overlay_video_segment["material_id"] == "VID_OVERLAY"
    assert len(lay.text_segments) == 2


def test_capture_baseline():
    ed = _editor()
    base = ed.capture_subtitle_baseline()
    assert base.found
    assert base.template_id == "3B4F9BD6-TMPL"
    assert base.template_effect_id == "7577568565935475985"
    assert base.font_resource_id == "7579481374890003713"
    assert abs(base.scale_x - 1.14) < 1e-6
    assert abs(base.transform_y - (-0.475)) < 1e-6


def test_apply_subtitle_layout_scale_and_offset():
    ed = _editor()
    # +10% ниже, масштаб 150%
    n = ed.apply_subtitle_layout(vertical_offset_percent=10.0, scale_percent=150.0)
    assert n == 2
    for seg in ed.layout.text_segments:
        sc = seg["clip"]["scale"]
        assert abs(sc["x"] - 1.14 * 1.5) < 1e-6
        assert abs(sc["y"] - 1.14 * 1.5) < 1e-6
        # +10% => dy = -0.2, y = -0.475 - 0.2
        assert abs(seg["clip"]["transform"]["y"] - (-0.475 - 0.2)) < 1e-6


def test_apply_subtitle_layout_noop_when_defaults():
    ed = _editor()
    ed.apply_subtitle_layout(vertical_offset_percent=0.0, scale_percent=100.0)
    for seg in ed.layout.text_segments:
        assert abs(seg["clip"]["scale"]["x"] - 1.14) < 1e-6
        assert abs(seg["clip"]["transform"]["y"] - (-0.475)) < 1e-6


def test_delete_subtitles():
    ed = _editor()
    removed = ed.delete_subtitles()
    assert removed == 2
    assert ed.layout.text_segments == []


def test_sync_to_voiceover_shortens():
    ed = _editor()
    ed.replace_voiceover  # noqa: B018 - ensure attribute exists
    # укоротим озвучку до 10 c и синхронизируем
    ed.layout.voiceover_segment["target_timerange"] = _tr(0, 10 * US)
    ed.layout.voiceover_segment["source_timerange"] = _tr(0, 10 * US)
    V = ed.sync_to_voiceover()
    assert V == 10 * US
    assert ed.doc.total_duration == 10 * US
    ed.clamp_segments_to_total()
    for track in ed.doc.tracks:
        for seg in track["segments"]:
            tr = seg["target_timerange"]
            assert tr["start"] + tr["duration"] <= 10 * US + 1


def test_reposition_overlay_in_window():
    ed = _editor()
    V = ed.doc.total_duration
    ed.reposition_overlay(40.0, 60.0)
    ov = ed.layout.overlay_video_segment
    tr = ov["target_timerange"]
    # клип целиком внутри окна 40..60% (с небольшим допуском на округление)
    assert tr["start"] >= int(V * 0.40) - 2
    assert tr["start"] + tr["duration"] <= int(V * 0.60) + 2


if __name__ == "__main__":
    import traceback

    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception:  # noqa: BLE001
            failed += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
