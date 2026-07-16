"""Оркестратор монтажа (отдельный процесс от озвучки).

Берёт готовую озвучку (mp3 + json с таймингами из папки voiceovers), подбирает
материалы из папок по шаблону и собирает видео — через FFmpeg (headless) или
CapCut (Windows). Число видео ограничивается `cycles`. Прогресс — в state,
поэтому продолжается после сбоя без потерь.
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml

from ..config import Config
from ..logging_setup import get_logger
from ..state import StateStore
from ..subtitles import Word, style_from_config, write_ass
from .media import probe_duration

log = get_logger("montage.orchestrator")


def _load_template(path: str | Path) -> dict:
    p = Path(path)
    if not p.exists():
        example = p.parent / "template.example.yaml"
        if example.exists():
            p = example
        else:
            return {}
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def _subtitle_style(template: dict, name: str = "glow_white"):
    styles = template.get("subtitle_styles", {})
    return style_from_config(styles.get(name, {}))


def _qr_from_template(template: dict) -> dict:
    for layer in template.get("layers", []):
        if layer.get("type") == "qr_overlay":
            return layer
    return {}


def _emoji_anims(template: dict) -> list[str]:
    for layer in template.get("layers", []):
        if layer.get("type") == "emoji":
            return layer.get("animations", ["zoom1"])
    return ["zoom1", "zoom2", "bounce1", "bounce2"]


def _words_from_json(data: dict) -> list[Word]:
    return [Word(w["word"], float(w["start"]), float(w["end"]))
            for w in data.get("words", [])]


def run_montage(cfg: Config, cycles: int, template_path: str = "template.yaml") -> list[str]:
    from ..assets import BackgroundSlicer, build_pools

    template = _load_template(template_path)
    state = StateStore(Path(cfg.state_dir) / "montage_state.json")
    pools = build_pools(cfg.folders, state)
    out_dir = Path(cfg.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    vo_dir = Path(cfg.voice.get("output_dir", "assets/voiceovers"))
    vo_jsons = sorted(vo_dir.glob("vo_*.json"))
    if not vo_jsons:
        log.warning("Нет озвучки в %s — сначала запусти процесс озвучки.", vo_dir)
        return []

    segment_sec = float(cfg.montage.get("background_segment_sec", 10))
    slicer = BackgroundSlicer(pools["backgrounds"], state, segment_sec)
    renderer = cfg.montage.get("renderer", "capcut")

    done = set(state.get("montage_done", []))
    style = _subtitle_style(template)
    qr_cfg = _qr_from_template(template)
    emoji_anims = _emoji_anims(template)

    produced: list[str] = []
    made = 0
    for vo_json in vo_jsons:
        if made >= cycles:
            break
        key = vo_json.name
        if key in done:
            continue
        try:
            out = _build_one(cfg, template, vo_json, pools, slicer, style,
                             qr_cfg, emoji_anims, out_dir, renderer, made)
            produced.append(str(out))
            done.add(key)
            state.set("montage_done", sorted(done))  # чекпоинт
            made += 1
        except Exception as exc:  # noqa: BLE001 - один битый ролик не рушит всё
            log.error("Видео для %s не собрано: %s", key, exc)
            continue

    log.info("Готово видео: %d", len(produced))
    return produced


def _build_one(cfg, template, vo_json, pools, slicer, style, qr_cfg,
               emoji_anims, out_dir, renderer, index):
    data = json.loads(vo_json.read_text(encoding="utf-8"))
    words = _words_from_json(data)
    duration = float(data.get("duration") or (words[-1].end if words else 10.0))

    audio = vo_json.with_suffix(".mp3")
    if not audio.exists():
        raise FileNotFoundError(f"Нет аудио рядом с {vo_json.name}")

    seg = slicer.next_segment(probe_duration)
    if seg is None:
        raise RuntimeError("Нет фонов в папке backgrounds.")
    bg, bg_start, bg_len = seg

    # субтитры
    ass_path = out_dir / f"video_{index:04d}.ass"
    wpc = 2
    for layer in template.get("layers", []):
        if layer.get("type") == "subtitles":
            wpc = int(layer.get("words_per_cue", 2))
    write_ass(words, style, ass_path,
              play_res=(int(cfg.video.get("width", 1080)),
                        int(cfg.video.get("height", 1920))),
              words_per_cue=wpc)

    # материалы
    emoji = pools["emojis"].next() if "emojis" in pools else None
    swoosh = pools["sounds"].next() if "sounds" in pools else None
    qr = pools["qr"].next() if "qr" in pools else None
    music = pools["music"].next() if "music" in pools else None

    out_path = out_dir / f"video_{index:04d}.mp4"

    if renderer == "ffmpeg":
        return _render_ffmpeg(cfg, out_path, bg, bg_start, bg_len, audio,
                              ass_path, music, swoosh, emoji, emoji_anims, qr,
                              qr_cfg, duration)
    # capcut
    from .capcut_draft import build_draft
    from .capcut_export import export_draft
    draft = build_draft(cfg, out_path, bg, bg_start, bg_len, audio, words,
                        music, swoosh, emoji, qr, qr_cfg, duration)
    return export_draft(cfg, draft, out_path)


def _render_ffmpeg(cfg, out_path, bg, bg_start, bg_len, audio, ass_path, music,
                   swoosh, emoji, emoji_anims, qr, qr_cfg, duration):
    from .ffmpeg_render import EmojiHit, QrOverlay, VideoSpec, render_video

    emojis = []
    if emoji is not None:
        anim = emoji_anims[0] if emoji_anims else "zoom1"
        emojis.append(EmojiHit(path=str(emoji), start=0.2, duration=1.2,
                               anim=anim))
    qr_overlay = None
    if qr is not None:
        total = float(qr_cfg.get("total_sec", 1.2))
        qr_overlay = QrOverlay(
            path=str(qr), start=max(duration - total, 0.0), total=total,
            in_sec=float((qr_cfg.get("in_anim") or {}).get("sec", 0.2)),
            out_sec=float((qr_cfg.get("out_anim") or {}).get("sec", 0.2)),
            scale_grow=float(qr_cfg.get("scale_grow", 1.08)),
        )
    spec = VideoSpec(
        out_path=str(out_path), background=str(bg), bg_start=bg_start,
        bg_length=bg_len, voiceover=str(audio), subtitles_ass=str(ass_path),
        music=str(music) if music else None, swoosh=str(swoosh) if swoosh else None,
        emojis=emojis, qr=qr_overlay,
        width=int(cfg.video.get("width", 1080)),
        height=int(cfg.video.get("height", 1920)),
        fps=int(cfg.video.get("fps", 60)),
        blur=int(cfg.video.get("background_blur", 40)),
        content_aspect=tuple(cfg.video.get("content_aspect", [5, 6])),
        duration=duration,
    )
    return render_video(spec)
