"""Сборка проекта CapCut 8.7.0 клонированием эталонного черновика.

Идея: берём твой реальный проект (templates/capcut_reference_8.7.json) как
шаблон и подставляем в него новые материалы (фон, озвучку, субтитры с
таймингами, эмодзи, QR, звуки, музыку), сохраняя ВСЕ твои эффекты и анимации
(стиль «Сияние», «Зум/Качели/Осветление», блюр-фон) с их реальными ID.

Это надёжнее ручной сборки JSON: мы не выдумываем поля, а копируем твои же
рабочие объекты и меняем только пути/тексты/тайминги/длительности.

Структура эталона (по дорожкам):
  0 video  — блюр-фон (эффект «Размытие»), 2 сегмента (jump-cut ~2.17с)
  1 video  — основной фон, 2 сегмента
  2 video  — оверлеи: эмодзи (Зум) и QR (Зум+Осветление)
  3 text   — субтитры «Сияние», N реплик
  4 audio  — озвучка (голос)
  5 audio  — SFX: swoosh + акценты у эмодзи и QR
  6 audio  — фоновая музыка (тихо)
"""
from __future__ import annotations

import copy
import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from ..config import Config
from ..logging_setup import get_logger
from . import capcut_presets as P
from .media import probe_duration

log = get_logger("montage.capcut_clone")

US = 1_000_000
REF_PATH = Path(__file__).resolve().parents[3] / "templates" / "capcut_reference_8.7.json"


def _uid() -> str:
    return str(uuid.uuid4()).upper()


@dataclass
class CloneAssets:
    background: Path
    bg_start: float
    bg_length: float
    voiceover: Path
    words: list                       # list[Word] с .text/.start/.end
    emoji: Path | None
    emoji_anim: str
    qr: Path | None
    swoosh: Path | None
    accent_emoji: Path | None
    accent_qr: Path | None
    music: Path | None
    duration: float


def _load_reference() -> dict:
    if not REF_PATH.exists():
        raise FileNotFoundError(
            f"Нет эталонного проекта {REF_PATH}. Он нужен для сборки CapCut."
        )
    return json.loads(REF_PATH.read_text(encoding="utf-8"))


def _find_track(draft: dict, ttype: str, which: int = 0) -> dict | None:
    found = [t for t in draft.get("tracks", []) if t.get("type") == ttype]
    return found[which] if which < len(found) else None


def _mat_by_id(draft: dict, mid: str) -> dict | None:
    for cat in draft["materials"]:
        for it in draft["materials"][cat] or []:
            if isinstance(it, dict) and it.get("id") == mid:
                return it
    return None


def _set_video_material(mat: dict, path: Path, dur_us: int) -> None:
    d = probe_size_duration(path)
    mat["path"] = str(path)
    mat["material_name"] = path.name
    if d["width"]:
        mat["width"] = d["width"]
    if d["height"]:
        mat["height"] = d["height"]
    mat["duration"] = int(d["duration"] * US) if d["duration"] else dur_us


def probe_size_duration(path: Path) -> dict:
    """Размеры и длительность через ffprobe (без падений)."""
    from .media import ffprobe_bin
    import subprocess
    out = {"width": 0, "height": 0, "duration": 0.0}
    try:
        r = subprocess.run(
            [ffprobe_bin(), "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height:format=duration",
             "-of", "json", str(path)],
            capture_output=True, text=True, timeout=30, check=True)
        data = json.loads(r.stdout)
        st = (data.get("streams") or [{}])[0]
        out["width"] = int(st.get("width") or 0)
        out["height"] = int(st.get("height") or 0)
        out["duration"] = float(data.get("format", {}).get("duration") or 0.0)
    except Exception:  # noqa: BLE001
        pass
    return out


def build_clone(cfg: Config, out_path: Path, a: CloneAssets,
                words_per_cue: int = 2) -> Path:
    draft = _load_reference()
    dur_us = int(a.duration * US)
    draft["duration"] = dur_us

    # обновим версию платформы (без аппаратных id — они уже вычищены)
    for key in ("last_modified_platform", "platform"):
        p = draft.get(key) or {}
        p["app_version"] = (cfg.montage.get("capcut", {}) or {}).get("version", "8.7.0")

    _replace_backgrounds(draft, a, dur_us)
    _replace_overlays(draft, a, dur_us)
    _replace_subtitles(draft, a, words_per_cue)
    _replace_audio(draft, a, dur_us)

    # запись в папку черновиков CapCut
    from .capcut_draft import _default_drafts_dir
    name = out_path.stem or f"autoshorts-{int(time.time())}"
    draft_dir = _default_drafts_dir(cfg) / name
    draft_dir.mkdir(parents=True, exist_ok=True)
    draft["name"] = name
    (draft_dir / "draft_content.json").write_text(
        json.dumps(draft, ensure_ascii=False), encoding="utf-8")
    (draft_dir / "draft_meta_info.json").write_text(
        json.dumps({"draft_name": name, "draft_fold_path": str(draft_dir),
                    "tm_draft_create": int(time.time() * 1000),
                    "tm_draft_modified": int(time.time() * 1000)},
                   ensure_ascii=False), encoding="utf-8")
    log.info("CapCut-черновик (клон эталона) собран: %s", draft_dir)
    return draft_dir


def _rescale_two_segments(track: dict, jumpcut_us: int, dur_us: int,
                          src_start_us: int) -> None:
    """Два сегмента фона: 0..jumpcut и jumpcut..duration (jump-cut в начале)."""
    segs = track.get("segments") or []
    if not segs:
        return
    jc = min(jumpcut_us, dur_us)
    if len(segs) >= 2:
        segs[0]["target_timerange"] = {"start": 0, "duration": jc}
        segs[0]["source_timerange"] = {"start": src_start_us, "duration": jc}
        segs[1]["target_timerange"] = {"start": jc, "duration": dur_us - jc}
        segs[1]["source_timerange"] = {"start": src_start_us + jc,
                                       "duration": dur_us - jc}
        del segs[2:]
    else:
        segs[0]["target_timerange"] = {"start": 0, "duration": dur_us}
        segs[0]["source_timerange"] = {"start": src_start_us, "duration": dur_us}


def _replace_backgrounds(draft: dict, a: CloneAssets, dur_us: int) -> None:
    blur = _find_track(draft, "video", 0)
    main = _find_track(draft, "video", 1)
    jc = int(min(P.INTRO_JUMPCUT_SEC, a.duration) * US)
    src0 = int(a.bg_start * US)
    for track in (blur, main):
        if not track:
            continue
        # подставляем фон в материалы обоих сегментов
        for seg in track.get("segments", []):
            mat = _mat_by_id(draft, seg.get("material_id"))
            if mat and mat.get("type") in ("video", "photo"):
                _set_video_material(mat, a.background, dur_us)
        _rescale_two_segments(track, jc, dur_us, src0)


def _replace_overlays(draft: dict, a: CloneAssets, dur_us: int) -> None:
    overlay = _find_track(draft, "video", 2)
    if not overlay:
        return
    segs = overlay.get("segments") or []
    # seg0 — эмодзи, seg1 — QR (по структуре эталона)
    if segs and a.emoji:
        mat = _mat_by_id(draft, segs[0].get("material_id"))
        if mat:
            _set_video_material(mat, a.emoji, int(2.2 * US))
        _set_anim(draft, segs[0], a.emoji_anim, with_lighten=False)
    if len(segs) >= 2 and a.qr:
        mat = _mat_by_id(draft, segs[1].get("material_id"))
        if mat:
            _set_video_material(mat, a.qr, int(P.QR_TOTAL_SEC * US))
        # QR в самый конец
        qstart = max(dur_us - int(P.QR_TOTAL_SEC * US), 0)
        segs[1]["target_timerange"] = {"start": qstart,
                                       "duration": int(P.QR_TOTAL_SEC * US)}
        _set_anim(draft, segs[1], "zoom2", with_lighten=True)


def _set_anim(draft: dict, seg: dict, anim_key: str, with_lighten: bool) -> None:
    """Заменить материал sticker_animation у сегмента на выбранный пресет."""
    preset = P.ANIM.get(anim_key, P.ANIM["zoom1"])
    anims = [{
        "id": preset["id"], "type": preset["type"], "start": 0,
        "duration": preset["duration"], "resource_id": preset["id"],
        "third_resource_id": preset["id"], "source_platform": 1,
        "name": preset["name"], "category_id": preset["category_id"],
        "category_name": preset["category_name"], "panel": "video",
        "material_type": "video", "anim_adjust_params": None, "request_id": "",
        "platform": "all",
    }]
    if with_lighten:
        o = P.ANIM_OUT_LIGHTEN
        anims.append({
            "id": o["id"], "type": o["type"], "start": preset["duration"],
            "duration": o["duration"], "resource_id": o["id"],
            "third_resource_id": o["id"], "source_platform": 1,
            "name": o["name"], "category_id": o["category_id"],
            "category_name": o["category_name"], "panel": "video",
            "material_type": "video", "anim_adjust_params": None,
            "request_id": "", "platform": "all",
        })
    # находим существующий anim-материал среди extra_material_refs
    for ref_id in seg.get("extra_material_refs", []):
        mat = _mat_by_id(draft, ref_id)
        if mat and mat.get("type") == "sticker_animation":
            mat["animations"] = anims
            return
    # если не было — создаём и цепляем
    new = {"id": _uid(), "type": "sticker_animation", "animations": anims}
    draft["materials"]["material_animations"].append(new)
    seg.setdefault("extra_material_refs", []).append(new["id"])


def _build_word_info(group, cue_start_s: float) -> dict:
    """Собрать word_info (текст + слова с таймингами в мс относительно реплики).

    Между словами вставляются пробелы-токены, как в эталоне CapCut.
    """
    words = []
    parts = []
    loc = 0
    ranges = []
    for i, w in enumerate(group):
        st = int(round((w.start - cue_start_s) * 1000))
        en = int(round((w.end - cue_start_s) * 1000))
        if i > 0:
            words.append({"text": " ", "start_time": words[-1]["end_time"],
                          "end_time": words[-1]["end_time"]})
            parts.append(" ")
            loc += 1
        words.append({"text": w.text, "start_time": st, "end_time": en})
        ranges.append({"location": loc, "length": len(w.text),
                       "source_type": "unknown"})
        parts.append(w.text)
        loc += len(w.text)
    text = "".join(parts)
    end_ms = words[-1]["end_time"] if words else 0
    return {"text": text,
            "info": {"text": text, "start_time": 0, "end_time": end_ms,
                     "words": words},
            "ranges": ranges}


def _replace_subtitles(draft: dict, a: CloneAssets, wpc: int = 2) -> None:
    track = _find_track(draft, "text", 0)
    if not track:
        return
    proto_seg = (track.get("segments") or [None])[0]
    if not proto_seg:
        return
    proto_tpl = _mat_by_id(draft, proto_seg.get("material_id"))
    # прототип-реплика — это text_template (в 8.7 тип 'text_template_subtitle')
    if not proto_tpl or "text_template" not in str(proto_tpl.get("type", "")):
        return
    # связанные текст-материалы прототипа (по text_info_resources)
    proto_text_ids = [r.get("text_material_id")
                      for r in proto_tpl.get("text_info_resources", [])
                      if r.get("text_material_id")]
    proto_texts = {tid: _mat_by_id(draft, tid) for tid in proto_text_ids}
    proto_anim = None
    for rid in proto_seg.get("extra_material_refs", []):
        m = _mat_by_id(draft, rid)
        if m and m.get("type") == "sticker_animation":
            proto_anim = m
            break

    wpc = max(int(wpc), 1)
    groups = [a.words[i:i + wpc] for i in range(0, len(a.words), wpc)]
    groups = [g for g in groups if g]

    # соберём id старых материалов субтитров для удаления
    old_tpl_ids, old_text_ids, old_anim_ids = set(), set(), set()
    for s in track.get("segments", []):
        old_tpl_ids.add(s.get("material_id"))
        tpl = _mat_by_id(draft, s.get("material_id"))
        if tpl:
            for r in tpl.get("text_info_resources", []):
                if r.get("text_material_id"):
                    old_text_ids.add(r["text_material_id"])
        for rid in s.get("extra_material_refs", []):
            mm = _mat_by_id(draft, rid)
            if mm and mm.get("type") == "sticker_animation":
                old_anim_ids.add(rid)

    new_segments = []
    for g in groups:
        info = _build_word_info(g, g[0].start)
        start = int(g[0].start * US)
        dur = int(max(g[-1].end - g[0].start, 0.1) * US)

        tpl = copy.deepcopy(proto_tpl)
        tpl["id"] = _uid()
        tpl["origin_word_info"] = copy.deepcopy(info["info"])
        tpl["current_word_info"] = copy.deepcopy(info["info"])
        tpl["material_text_ranges"] = info["ranges"]
        # переносим связанные текст-материалы, переставляя id
        for tir in tpl.get("text_info_resources", []):
            old_tid = tir.get("text_material_id")
            src_text = proto_texts.get(old_tid)
            if src_text is None:
                continue
            new_text = copy.deepcopy(src_text)
            new_text["id"] = _uid()
            _set_text_content(new_text, info["text"])
            draft["materials"]["texts"].append(new_text)
            tir["text_material_id"] = new_text["id"]
            ai = tir.get("attach_info") or {}
            ai["start_time"] = 0
            ai["duration"] = dur
        draft["materials"]["text_templates"].append(tpl)

        seg = copy.deepcopy(proto_seg)
        seg["id"] = _uid()
        seg["material_id"] = tpl["id"]
        seg["target_timerange"] = {"start": start, "duration": dur}
        seg["source_timerange"] = {"start": 0, "duration": dur}

        new_refs = []
        for r in seg.get("extra_material_refs", []):
            mm = _mat_by_id(draft, r)
            if mm and mm.get("type") == "sticker_animation" and proto_anim:
                amat = copy.deepcopy(proto_anim)
                amat["id"] = _uid()
                for an in amat.get("animations", []):
                    an["duration"] = dur
                draft["materials"]["material_animations"].append(amat)
                new_refs.append(amat["id"])
            else:
                new_refs.append(r)
        seg["extra_material_refs"] = new_refs
        new_segments.append(seg)

    # удаляем старые материалы субтитров
    draft["materials"]["text_templates"] = [
        t for t in draft["materials"]["text_templates"]
        if t.get("id") not in old_tpl_ids]
    draft["materials"]["texts"] = [
        t for t in draft["materials"]["texts"] if t.get("id") not in old_text_ids]
    draft["materials"]["material_animations"] = [
        m for m in draft["materials"]["material_animations"]
        if m.get("id") not in old_anim_ids]

    track["segments"] = new_segments


def _set_text_content(tmat: dict, text: str) -> None:
    """Заменить текст в поле content (вложенный JSON) и длину range."""
    try:
        content = json.loads(tmat.get("content") or "{}")
        content["text"] = text
        for st in content.get("styles", []):
            st["range"] = [0, len(text)]
        tmat["content"] = json.dumps(content, ensure_ascii=False)
    except (json.JSONDecodeError, TypeError):
        tmat["content"] = json.dumps({"text": text}, ensure_ascii=False)
    # дублирующие поля материала текста
    if "words" in tmat:
        tmat["words"] = {"text": [text], "start_time": [], "end_time": []} \
            if isinstance(tmat.get("words"), dict) else tmat.get("words")


def _replace_audio(draft: dict, a: CloneAssets, dur_us: int) -> None:
    # track4 — голос
    voice = _find_track(draft, "audio", 0)
    if voice and voice.get("segments"):
        seg = voice["segments"][0]
        mat = _mat_by_id(draft, seg.get("material_id"))
        if mat:
            mat["path"] = str(a.voiceover)
            mat["name"] = a.voiceover.name
            mat["duration"] = dur_us
        seg["target_timerange"] = {"start": 0, "duration": dur_us}
        seg["source_timerange"] = {"start": 0, "duration": dur_us}

    # track5 — SFX: swoosh + акценты
    sfx = _find_track(draft, "audio", 1)
    if sfx and sfx.get("segments"):
        segs = sfx["segments"]
        mapping = [a.swoosh, a.accent_emoji, a.accent_qr]
        for seg, snd in zip(segs, mapping):
            if not snd:
                continue
            mat = _mat_by_id(draft, seg.get("material_id"))
            if mat:
                mat["path"] = str(snd)
                mat["name"] = snd.name
        # QR-акцент — к концу
        if len(segs) >= 3:
            segs[2]["target_timerange"] = {
                "start": max(dur_us - int(1.0 * US), 0),
                "duration": int(0.9 * US)}

    # track6 — музыка (тихо, растянуть/обрезать под длину)
    music = _find_track(draft, "audio", 2)
    if music and music.get("segments") and a.music:
        seg = music["segments"][0]
        mat = _mat_by_id(draft, seg.get("material_id"))
        if mat:
            mat["path"] = str(a.music)
            mat["name"] = a.music.name
        seg["target_timerange"] = {"start": 0, "duration": dur_us}
