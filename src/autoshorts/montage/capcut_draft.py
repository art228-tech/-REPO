"""Сборка проекта (черновика) CapCut программно.

CapCut хранит проект как папку с draft_content.json (в 8.7 — многофайловое
хранилище). Мы формируем таймлайн из готовых ассетов: основной фон, озвучка,
текст-субтитры, эмодзи, QR. Дальше проект открывается в CapCut и экспортируется
(см. capcut_export.py).

ВАЖНО: точная схема полей CapCut 8.7.0 обширна и меняется между версиями.
Здесь собран рабочий каркас черновика; финально его надо открыть в твоём CapCut
и, если какие-то поля версия не примет, поправить в _material_*/_segment_*.
Схема вынесена в отдельные функции именно ради быстрой правки под версию.
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from ..config import Config
from ..logging_setup import get_logger

log = get_logger("montage.capcut_draft")

US = 1_000_000  # CapCut считает время в микросекундах


def _uid() -> str:
    return str(uuid.uuid4()).upper()


def _default_drafts_dir(cfg: Config) -> Path:
    configured = (cfg.montage.get("capcut", {}) or {}).get("drafts_dir")
    if configured:
        return Path(configured)
    # Windows по умолчанию
    import os
    local = os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local"))
    return Path(local) / "CapCut" / "User Data" / "Projects" / "com.lveditor.draft"


def _video_material(path: Path, duration_us: int) -> dict:
    return {
        "id": _uid(), "type": "video", "path": str(path),
        "material_name": path.name, "duration": duration_us,
        "width": 0, "height": 0, "crop_scale": 1.0,
    }


def _audio_material(path: Path, duration_us: int) -> dict:
    return {
        "id": _uid(), "type": "extract_music", "path": str(path),
        "material_name": path.name, "duration": duration_us,
    }


def _text_material(text: str, style: dict | None = None) -> dict:
    return {
        "id": _uid(), "type": "text", "content": text,
        "font_size": (style or {}).get("font_size", 12),
        "text_color": (style or {}).get("color", "#FFFFFF"),
    }


def _sticker_material(path: Path) -> dict:
    return {"id": _uid(), "type": "image", "path": str(path),
            "material_name": path.name}


def _segment(material_id: str, start_us: int, dur_us: int,
             render_index: int = 0) -> dict:
    return {
        "id": _uid(), "material_id": material_id,
        "target_timerange": {"start": start_us, "duration": dur_us},
        "source_timerange": {"start": 0, "duration": dur_us},
        "render_index": render_index, "visible": True,
        "clip": {"scale": {"x": 1.0, "y": 1.0},
                 "transform": {"x": 0.0, "y": 0.0}, "alpha": 1.0},
    }


def build_draft(cfg: Config, out_path: Path, bg: Path, bg_start: float,
                bg_len: float, audio: Path, words, music, swoosh, emoji,
                emoji_anim, qr, qr_cfg: dict, duration: float) -> Path:
    """Собрать папку черновика CapCut и вернуть путь к ней."""
    drafts_dir = _default_drafts_dir(cfg)
    name = out_path.stem or f"autoshorts-{int(time.time())}"
    draft_dir = drafts_dir / name
    draft_dir.mkdir(parents=True, exist_ok=True)

    W = int(cfg.video.get("width", 1080))
    H = int(cfg.video.get("height", 1920))
    FPS = int(cfg.video.get("fps", 60))
    dur_us = int(duration * US)

    materials = {"videos": [], "audios": [], "texts": [], "images": []}
    tracks = []

    # видео-дорожка: основной фон
    vmat = _video_material(bg, dur_us)
    materials["videos"].append(vmat)
    tracks.append({"id": _uid(), "type": "video",
                   "segments": [_segment(vmat["id"], 0, dur_us)]})

    # аудио-дорожка: озвучка (+ swoosh в начале)
    amat = _audio_material(audio, dur_us)
    materials["audios"].append(amat)
    audio_segments = [_segment(amat["id"], 0, dur_us)]
    if swoosh:
        smat = _audio_material(Path(swoosh), int(0.6 * US))
        materials["audios"].append(smat)
        audio_segments.append(_segment(smat["id"], 0, int(0.6 * US)))
    tracks.append({"id": _uid(), "type": "audio", "segments": audio_segments})

    # текст-дорожка: субтитры по 2 слова
    text_segments = []
    for i in range(0, len(words), 2):
        group = words[i:i + 2]
        if not group:
            continue
        tmat = _text_material(" ".join(w.text for w in group))
        materials["texts"].append(tmat)
        start = int(group[0].start * US)
        dur = int((group[-1].end - group[0].start) * US)
        text_segments.append(_segment(tmat["id"], start, max(dur, 1)))
    if text_segments:
        tracks.append({"id": _uid(), "type": "text", "segments": text_segments})

    # эмодзи (1 шт., на переходе в начале, случайная комбо-анимация)
    if emoji:
        emat = _sticker_material(Path(emoji))
        materials["images"].append(emat)
        emo_seg = _segment(emat["id"], int(0.2 * US), int(1.2 * US))
        # Имя пресета анимации (zoom1/zoom2/bounce1/bounce2). Реальный ID пресета
        # CapCut подставим после разбора эталонного проекта на твоём ноуте.
        emo_seg["animation_preset"] = emoji_anim
        tracks.append({"id": _uid(), "type": "sticker", "segments": [emo_seg]})

    # QR в конце
    if qr:
        qmat = _sticker_material(Path(qr))
        materials["images"].append(qmat)
        total = float(qr_cfg.get("total_sec", 1.2))
        qstart = int(max(duration - total, 0.0) * US)
        tracks.append({"id": _uid(), "type": "sticker",
                       "segments": [_segment(qmat["id"], qstart,
                                             int(total * US))]})

    draft_content = {
        "id": _uid(),
        "canvas_config": {"width": W, "height": H, "ratio": "original"},
        "fps": FPS,
        "duration": dur_us,
        "materials": materials,
        "tracks": tracks,
        "platform": {"app_version": (cfg.montage.get("capcut", {}) or {})
                     .get("version", "8.7.0")},
    }

    (draft_dir / "draft_content.json").write_text(
        json.dumps(draft_content, ensure_ascii=False, indent=2), encoding="utf-8")
    # Мета-файл, который CapCut использует для списка проектов.
    (draft_dir / "draft_meta_info.json").write_text(
        json.dumps({"draft_name": name, "draft_fold_path": str(draft_dir),
                    "tm_draft_create": int(time.time() * 1000)},
                   ensure_ascii=False, indent=2), encoding="utf-8")

    log.info("Черновик CapCut собран: %s", draft_dir)
    log.warning("Открой проект в CapCut 8.7.0 и проверь таймлайн — при "
                "несовпадении полей версии поправим схему в capcut_draft.py.")
    return draft_dir
