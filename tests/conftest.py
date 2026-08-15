"""Синтетический черновик, повторяющий устройство настоящих шаблонов.

Настоящие проекты весят сотни мегабайт и содержат тексты пользователя, поэтому
для тестов собирается минимальная копия той же формы: фон с размытием, резкое
наложение, смайлик с хромакеем, QR с кейфреймами, озвучка, три акцента, музыка
и дорожка субтитров.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

US = 1_000_000
GUID = "0E685133-18CE-45ED-8CB8-2904A212EC80"


def _placeholder(subdir: str, name: str) -> str:
    return f"##_draftpath_placeholder_{GUID}_##/{subdir}/{name}"


def _segment(material_id: str, start: int, duration: int, *, source_start: int = 0,
             source_duration: int | None = None, refs=(), scale: float | None = None,
             offset_y: float = 0.0, volume: float | None = None, render_index: int = 0,
             keyframes=None) -> dict:
    segment = {
        "id": f"SEG-{material_id}-{start}",
        "material_id": material_id,
        "target_timerange": {"start": start, "duration": duration},
        "source_timerange": {"start": source_start, "duration": source_duration or duration},
        "extra_material_refs": list(refs),
        "render_index": render_index,
        "visible": True,
        "speed": 1.0,
    }
    if scale is not None:
        segment["clip"] = {
            "scale": {"x": scale, "y": scale},
            "transform": {"x": 0.0, "y": offset_y},
            "rotation": 0.0,
            "alpha": 1.0,
            "flip": {"horizontal": False, "vertical": False},
        }
    if volume is not None:
        segment["volume"] = volume
    if keyframes:
        segment["common_keyframes"] = keyframes
    return segment


def _text_content(text: str) -> str:
    return json.dumps({
        "styles": [{"range": [0, len(text)], "size": 12,
                    "fill": {"content": {"solid": {"color": [1, 1, 1]}}}}],
        "text": text,
    }, ensure_ascii=False)


def make_draft(*, with_music: bool = True) -> dict:
    cut = 2_400_000
    total = 12_800_000
    subtitle_texts = ["первая реплика шаблона", "вторая реплика чуть длиннее", "третья"]

    speeds = [{"id": f"SPD{i}", "type": "speed", "speed": 1.0, "mode": 0} for i in range(8)]
    speeds[5]["speed"] = 1.3

    materials = {
        "videos": [
            {"id": "VID_BG0", "type": "video", "material_name": "gameplay.mp4",
             "path": _placeholder("video", "gameplay.mp4"), "duration": 300 * US,
             "width": 1280, "height": 576, "has_audio": True},
            {"id": "VID_BG1", "type": "video", "material_name": "gameplay.mp4",
             "path": _placeholder("video", "gameplay.mp4"), "duration": 300 * US,
             "width": 1280, "height": 576, "has_audio": True},
            {"id": "VID_OV0", "type": "video", "material_name": "gameplay.mp4",
             "path": _placeholder("video", "gameplay.mp4"), "duration": 300 * US,
             "width": 1280, "height": 576, "has_audio": True},
            {"id": "VID_OV1", "type": "video", "material_name": "gameplay.mp4",
             "path": _placeholder("video", "gameplay.mp4"), "duration": 300 * US,
             "width": 1280, "height": 576, "has_audio": True},
            {"id": "VID_EMOJI", "type": "video", "material_name": "emoji.mp4",
             "path": _placeholder("video", "emoji.mp4"), "duration": 3 * US,
             "width": 1080, "height": 1080, "has_audio": False},
            {"id": "VID_QR", "type": "photo", "material_name": "qr.png",
             "path": _placeholder("video", "qr.png"), "duration": 10800 * US,
             "width": 512, "height": 512, "has_audio": False},
        ],
        "audios": [
            {"id": "AUD_VOICE", "type": "extract_music", "name": "voice.mp3",
             "path": _placeholder("audio", "voice.mp3"), "duration": 12_900_000},
            {"id": "AUD_SWOOSH", "type": "music", "name": "Woosh",
             "path": _placeholder("audio", "woosh.m4a"), "duration": 1 * US},
            {"id": "AUD_STICKER", "type": "extract_music", "name": "bell.mp3",
             "path": _placeholder("audio", "bell.mp3"), "duration": 1_900_000},
            {"id": "AUD_QR", "type": "extract_music", "name": "wow.mp3",
             "path": _placeholder("audio", "wow.mp3"), "duration": 1_800_000},
            {"id": "AUD_MUSIC", "type": "music", "name": "background track",
             "path": _placeholder("audio", "music.mp3"), "duration": 119 * US},
        ],
        "speeds": speeds,
        "chromas": [{"id": "CHR0", "type": "chroma", "color": "#00D700FF"}],
        "video_effects": [
            {"id": "EFF0", "type": "video_effect", "name": "Размытие",
             "adjust_params": [{"name": "effects_adjust_blur", "value": 0.36}]},
            {"id": "EFF1", "type": "video_effect", "name": "Размытие",
             "adjust_params": [{"name": "effects_adjust_blur", "value": 0.42}]},
        ],
        "material_animations": [
            {"id": "ANI_OVERLAY", "type": "sticker_animation",
             "animations": [{"type": "in", "name": "Зум 1", "start": 0, "duration": 500_000}]},
            {"id": "ANI_EMOJI", "type": "sticker_animation",
             "animations": [{"type": "group", "name": "Зум 1", "start": 0, "duration": 2_308_000}]},
            {"id": "ANI_QR", "type": "sticker_animation",
             "animations": [{"type": "in", "name": "Зум 1", "start": 0, "duration": 220_000},
                            {"type": "out", "name": "Осветление", "start": 800_000, "duration": 220_000}]},
        ],
        "texts": [],
        "text_templates": [],
    }

    for index, text in enumerate(subtitle_texts):
        materials["texts"].append({
            "id": f"TXT{index}", "type": "text", "recognize_text": text,
            "content": _text_content(text), "language": "ru-RU",
            "group_id": "ru-RU_1", "recognize_task_id": "task",
            "words": {"start_time": [0], "end_time": [500], "text": [text.split()[0]]},
        })
        materials["material_animations"].append({
            "id": f"ANI_SUB{index}", "type": "sticker_animation",
            "animations": [{"type": "caption", "name": "", "start": 0, "duration": 1_500_000}],
        })
        materials["text_templates"].append({
            "id": f"TTP{index}", "type": "text_template_subtitle",
            "name": "cc_style", "resource_id": "7547393318032903425",
            "text_info_resources": [{
                "text_material_id": f"TXT{index}",
                "extra_material_refs": [f"ANI_SUB{index}"],
                "attach_info": {"start_time": 0, "duration": 1_500_000,
                                "original_size_width": 574.0, "original_size_height": 120.0},
            }],
        })

    keyframes = [
        {"id": "KF_X", "property_type": "KFTypePositionX",
         "keyframe_list": [{"time_offset": 3000, "values": [0.0]},
                           {"time_offset": 1_100_000, "values": [0.0]}]},
        {"id": "KF_Y", "property_type": "KFTypePositionY",
         "keyframe_list": [{"time_offset": 3000, "values": [0.21]},
                           {"time_offset": 1_100_000, "values": [0.21]}]},
    ]

    common = ["SPD0", "CHR0"]
    tracks = [
        {"type": "video", "flag": 0, "segments": [
            _segment("VID_BG0", 0, cut, source_start=25 * US, refs=["SPD0", "EFF0"], scale=4.0),
            _segment("VID_BG1", cut, total - cut, source_start=28 * US, refs=["SPD1", "EFF1"], scale=4.1),
        ]},
        {"type": "audio", "flag": 0, "segments": [
            _segment("AUD_VOICE", 7000, 12_700_000, refs=["SPD2"], volume=1.0),
        ]},
        {"type": "audio", "flag": 0, "segments": [
            _segment("AUD_SWOOSH", cut - 190_000, 1 * US, refs=["SPD3"], volume=0.45),
            _segment("AUD_STICKER", 5_690_000, 1_900_000, refs=["SPD4"], volume=0.40),
            _segment("AUD_QR", 11_600_000, 1_100_000, refs=["SPD7"], volume=0.32),
        ]},
        {"type": "video", "flag": 2, "segments": [
            _segment("VID_OV0", 0, cut, source_start=25 * US, refs=["SPD6"], scale=2.67),
            _segment("VID_OV1", cut, total - cut, source_start=28 * US,
                     refs=["SPD6", "ANI_OVERLAY"], scale=2.67),
        ]},
        {"type": "video", "flag": 2, "segments": [
            _segment("VID_EMOJI", 5_667_000, 2_308_000, source_duration=3 * US,
                     refs=["SPD5", "CHR0", "ANI_EMOJI"], scale=0.66, offset_y=0.27),
            _segment("VID_QR", 11_600_000, 1_100_000, refs=["SPD7", "ANI_QR"],
                     scale=0.49, offset_y=0.21, keyframes=keyframes),
        ]},
        {"type": "sticker", "flag": 1, "segments": [
            _segment(f"TTP{i}", 200_000 + i * 2_000_000, 1_500_000,
                     refs=[f"ANI_SUB{i}"], scale=1.06, offset_y=-0.51, render_index=14000 + i)
            for i in range(len(subtitle_texts))
        ]},
    ]

    if with_music:
        tracks.insert(3, {"type": "audio", "flag": 0, "segments": [
            _segment("AUD_MUSIC", 0, total - 90_000, source_start=5 * US, refs=["SPD7"], volume=0.06),
        ]})

    return {
        "id": "DRAFT-TEST",
        "version": 360000,
        "name": "fixture",
        "duration": total,
        "fps": 30.0,
        "canvas_config": {"width": 1080, "height": 1920, "ratio": "original"},
        "platform": {"app_source": "cc", "app_version": "8.1.1"},
        "materials": materials,
        "tracks": tracks,
        "subtitle_taskinfo": [],
    }


@pytest.fixture
def template_folder(tmp_path: Path) -> Path:
    """Папка проекта с медиафайлами-заглушками."""
    folder = tmp_path / "0813-99"
    (folder / "video").mkdir(parents=True)
    (folder / "audio").mkdir(parents=True)

    for name in ("gameplay.mp4", "emoji.mp4", "qr.png"):
        (folder / "video" / name).write_bytes(b"\x00" * 64)
    for name in ("voice.mp3", "woosh.m4a", "bell.mp3", "wow.mp3", "music.mp3"):
        (folder / "audio" / name).write_bytes(b"\x00" * 64)

    payload = json.dumps(make_draft(), ensure_ascii=False, separators=(",", ":"))
    (folder / "draft_content.json").write_text(payload, encoding="utf-8")
    (folder / "template-2.tmp").write_text(payload, encoding="utf-8")
    (folder / "draft_content.json.bak").write_text(payload, encoding="utf-8")
    (folder / "draft_meta_info.json").write_text(json.dumps({
        "draft_id": "old", "draft_name": "0813-99",
        "draft_fold_path": str(folder), "draft_root_path": str(folder.parent),
        "tm_duration": 12_800_000,
        "draft_materials": [{"type": 0, "value": [
            {"id": "M1", "type": 0, "metetype": "extract_music", "duration": 12_900_000,
             "extra_info": "voice.mp3", "file_Path": "./audio/voice.mp3"},
        ]}],
    }, ensure_ascii=False), encoding="utf-8")
    return folder
