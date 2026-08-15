"""Разбор шаблона: кто есть кто на таймлайне.

Роли определяются по признакам, а не по номерам дорожек. Это принципиально:
в одном из шаблонов нет фоновой музыки, из-за чего нумерация съезжает, и любой
жёстко прописанный индекс сломался бы. Признаки взяты из разбора шести реальных
проектов.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .draft_io import Draft
from .errors import TemplateError
from .logging_setup import get_logger
from .units import fmt, us2s

log = get_logger("profile")


@dataclass(frozen=True)
class SegRef:
    """Адрес сегмента на таймлайне."""

    track: int
    index: int

    def get(self, draft: Draft) -> dict:
        return draft.tracks[self.track]["segments"][self.index]


@dataclass
class VideoSlot:
    """Место под клип: один и тот же файл на фоне и в резком наложении."""

    background: SegRef
    overlay: SegRef
    background_scale: float
    overlay_scale: float
    duration_us: int


@dataclass
class DecorSpec:
    """Смайлик или QR вместе со своим звуком."""

    segment: SegRef
    start_us: int
    duration_us: int
    source_duration_us: int
    speed: float
    scale: float
    offset_x: float
    offset_y: float
    animation_ids: list[str] = field(default_factory=list)
    sfx: SegRef | None = None
    sfx_offset_us: int = 0
    sfx_duration_us: int = 0
    sfx_volume: float = 1.0


@dataclass
class SubtitleStyle:
    """Эталонный субтитр, от которого наследуется оформление."""

    track: int
    template_material_id: str
    text_material_id: str
    animation_id: str | None
    scale: float
    offset_x: float
    offset_y: float
    render_index: int
    metrics: list[tuple[int, float, float]] = field(default_factory=list)
    """Тройки (длина текста, ширина, высота) из шаблона — для подбора размеров."""


@dataclass
class TemplateProfile:
    name: str
    folder: Path
    total_us: int
    fps: float
    width: int
    height: int

    cut_us: int
    slots: list[VideoSlot]

    voice: SegRef
    voice_start_us: int
    voice_duration_us: int
    tail_after_voice_us: int

    swoosh: SegRef | None
    swoosh_offset_us: int
    swoosh_duration_us: int

    sticker: DecorSpec | None
    qr: DecorSpec | None

    music: SegRef | None
    music_tail_us: int
    music_source_start_us: int
    music_volume: float

    subtitles: SubtitleStyle | None
    subtitle_count: int

    gameplay_material_ids: list[str] = field(default_factory=list)
    voice_material_id: str = ""

    def describe(self) -> str:
        lines = [
            f"шаблон {self.name}: {fmt(self.total_us)}, {self.width}x{self.height}, {self.fps:g} к/с",
            f"  стык на {fmt(self.cut_us)}; хвост после озвучки {fmt(self.tail_after_voice_us)}",
        ]
        for index, slot in enumerate(self.slots):
            lines.append(
                f"  слот {index + 1}: {fmt(slot.duration_us)}, "
                f"фон x{slot.background_scale:.3f}, наложение x{slot.overlay_scale:.3f}"
            )
        if self.swoosh:
            lines.append(f"  свуш: смещение от стыка {us2s(self.swoosh_offset_us):+.3f}с")
        if self.sticker:
            lines.append(
                f"  стикер: старт {fmt(self.sticker.start_us)}, скорость {self.sticker.speed:.2f}, "
                f"по вертикали {self.sticker.offset_y:+.4f}"
            )
        if self.qr:
            lines.append(
                f"  QR: старт {fmt(self.qr.start_us)}, длительность {fmt(self.qr.duration_us)}, "
                f"по вертикали {self.qr.offset_y:+.4f}"
            )
        if self.music:
            lines.append(f"  музыка: громкость {self.music_volume:.3f}")
        lines.append(f"  субтитров в шаблоне: {self.subtitle_count}")
        return "\n".join(lines)


def _segments(track: dict) -> list[dict]:
    return track.get("segments") or []


def _target(segment: dict) -> tuple[int, int]:
    tr = segment.get("target_timerange") or {}
    return int(tr.get("start") or 0), int(tr.get("duration") or 0)


def _scale(segment: dict) -> float:
    clip = segment.get("clip") or {}
    return float((clip.get("scale") or {}).get("x") or 1.0)


def _transform(segment: dict) -> tuple[float, float]:
    clip = segment.get("clip") or {}
    tr = clip.get("transform") or {}
    return float(tr.get("x") or 0.0), float(tr.get("y") or 0.0)


def _refs_of_section(draft: Draft, segment: dict, section: str) -> list[dict]:
    index = draft.material_index()
    found = []
    for ref in segment.get("extra_material_refs") or []:
        entry = index.get(ref)
        if entry and entry[0] == section:
            found.append(entry[1])
    return found


def _speed_of(draft: Draft, segment: dict) -> float:
    speeds = _refs_of_section(draft, segment, "speeds")
    for speed in speeds:
        value = float(speed.get("speed") or 1.0)
        if abs(value - 1.0) > 1e-6:
            return value
    return 1.0


def analyse(folder: Path) -> TemplateProfile:
    """Строит профиль шаблона по папке проекта."""
    draft = Draft.load(folder)
    tracks = draft.tracks
    index = draft.material_index()

    audio_tracks = [i for i, t in enumerate(tracks) if t.get("type") == "audio"]
    video_tracks = [i for i, t in enumerate(tracks) if t.get("type") == "video"]
    sticker_tracks = [i for i, t in enumerate(tracks) if t.get("type") == "sticker"]

    background_track = _pick_background(tracks, video_tracks)
    decor_track = _pick_decor(draft, tracks, video_tracks, background_track)
    overlay_track = _pick_overlay(tracks, video_tracks, background_track, decor_track)

    voice_track, music_track, sfx_track = _split_audio(draft, tracks, audio_tracks)

    background_segments = _segments(tracks[background_track])
    overlay_segments = _segments(tracks[overlay_track])
    if len(background_segments) < 2 or len(overlay_segments) < 2:
        raise TemplateError(
            f"{folder.name}: ожидались два фрагмента на фоне и в наложении, "
            f"нашлось {len(background_segments)} и {len(overlay_segments)}"
        )

    cut_us, _ = _target(background_segments[1])
    slots = [
        VideoSlot(
            background=SegRef(background_track, i),
            overlay=SegRef(overlay_track, i),
            background_scale=_scale(background_segments[i]),
            overlay_scale=_scale(overlay_segments[i]),
            duration_us=_target(background_segments[i])[1],
        )
        for i in (0, 1)
    ]

    voice_segment = _segments(tracks[voice_track])[0]
    voice_start, voice_duration = _target(voice_segment)
    total_us = int(draft.duration_us)

    sticker, qr = _decor(draft, tracks, decor_track)
    swoosh, sticker_sfx, qr_sfx = _assign_sfx(
        tracks, sfx_track, cut_us,
        sticker.start_us if sticker else None,
        qr.start_us if qr else None,
    )

    if sticker and sticker_sfx is not None:
        segment = sticker_sfx.get(draft)
        start, duration = _target(segment)
        sticker.sfx = sticker_sfx
        sticker.sfx_offset_us = start - sticker.start_us
        sticker.sfx_duration_us = duration
        sticker.sfx_volume = float(segment.get("volume") or 1.0)

    if qr and qr_sfx is not None:
        segment = qr_sfx.get(draft)
        start, duration = _target(segment)
        qr.sfx = qr_sfx
        qr.sfx_offset_us = start - qr.start_us
        qr.sfx_duration_us = duration
        qr.sfx_volume = float(segment.get("volume") or 1.0)

    swoosh_offset = 0
    swoosh_duration = 0
    if swoosh is not None:
        start, duration = _target(swoosh.get(draft))
        swoosh_offset = start - cut_us
        swoosh_duration = duration

    music_ref = None
    music_tail = 0
    music_source_start = 0
    music_volume = 0.06
    if music_track is not None:
        music_ref = SegRef(music_track, 0)
        segment = music_ref.get(draft)
        start, duration = _target(segment)
        music_tail = total_us - (start + duration)
        music_source_start = int((segment.get("source_timerange") or {}).get("start") or 0)
        music_volume = float(segment.get("volume") or 0.06)

    subtitles, subtitle_count = _subtitles(draft, tracks, sticker_tracks)

    gameplay_ids = [
        background_segments[0].get("material_id"),
        background_segments[1].get("material_id"),
        overlay_segments[0].get("material_id"),
        overlay_segments[1].get("material_id"),
    ]

    profile = TemplateProfile(
        name=folder.name,
        folder=Path(folder),
        total_us=total_us,
        fps=float(draft.content.get("fps") or 30.0),
        width=int((draft.content.get("canvas_config") or {}).get("width") or 1080),
        height=int((draft.content.get("canvas_config") or {}).get("height") or 1920),
        cut_us=cut_us,
        slots=slots,
        voice=SegRef(voice_track, 0),
        voice_start_us=voice_start,
        voice_duration_us=voice_duration,
        tail_after_voice_us=total_us - (voice_start + voice_duration),
        swoosh=swoosh,
        swoosh_offset_us=swoosh_offset,
        swoosh_duration_us=swoosh_duration,
        sticker=sticker,
        qr=qr,
        music=music_ref,
        music_tail_us=music_tail,
        music_source_start_us=music_source_start,
        music_volume=music_volume,
        subtitles=subtitles,
        subtitle_count=subtitle_count,
        gameplay_material_ids=[mid for mid in gameplay_ids if mid],
        voice_material_id=voice_segment.get("material_id", ""),
    )

    log.debug("%s", profile.describe())
    return profile


def _pick_background(tracks: list[dict], video_tracks: list[int]) -> int:
    for i in video_tracks:
        if int(tracks[i].get("flag") or 0) == 0 and len(_segments(tracks[i])) >= 2:
            return i
    raise TemplateError("Не нашёл дорожку фона: нужна видеодорожка с flag=0 и двумя сегментами")


def _pick_decor(draft: Draft, tracks: list[dict], video_tracks: list[int], background: int) -> int:
    index = draft.material_index()
    for i in video_tracks:
        if i == background:
            continue
        for segment in _segments(tracks[i]):
            material = index.get(segment.get("material_id"), (None, {}))[1]
            if material.get("type") == "photo":
                return i
            if _refs_of_section(draft, segment, "chromas"):
                return i
    raise TemplateError("Не нашёл дорожку со смайликом и QR: нет ни фото, ни хромакея")


def _pick_overlay(tracks: list[dict], video_tracks: list[int], background: int, decor: int) -> int:
    candidates = [i for i in video_tracks if i not in (background, decor) and len(_segments(tracks[i])) >= 2]
    if not candidates:
        raise TemplateError("Не нашёл дорожку резкого наложения")
    return candidates[0]


def _split_audio(draft: Draft, tracks: list[dict], audio_tracks: list[int]):
    """Разводит аудиодорожки по ролям: озвучка, музыка, звуковые акценты."""
    if not audio_tracks:
        raise TemplateError("В шаблоне нет ни одной аудиодорожки")

    sfx = max(audio_tracks, key=lambda i: len(_segments(tracks[i])))
    if len(_segments(tracks[sfx])) < 2:
        raise TemplateError("Не нашёл дорожку со звуковыми акцентами")

    singles = [i for i in audio_tracks if i != sfx and len(_segments(tracks[i])) == 1]
    if not singles:
        raise TemplateError("Не нашёл дорожку озвучки")

    def volume(track_index: int) -> float:
        return float(_segments(tracks[track_index])[0].get("volume") or 1.0)

    voice = max(singles, key=volume)
    music_candidates = [i for i in singles if i != voice and volume(i) < 0.5]
    music = music_candidates[0] if music_candidates else None
    return voice, music, sfx


def _decor(draft: Draft, tracks: list[dict], decor_track: int):
    """Разбирает дорожку со смайликом и QR."""
    index = draft.material_index()
    sticker = qr = None

    for position, segment in enumerate(_segments(tracks[decor_track])):
        material = index.get(segment.get("material_id"), (None, {}))[1]
        start, duration = _target(segment)
        source = segment.get("source_timerange") or {}
        offset_x, offset_y = _transform(segment)
        animations = [
            item.get("id")
            for item in _refs_of_section(draft, segment, "material_animations")
            if item.get("id")
        ]
        spec = DecorSpec(
            segment=SegRef(decor_track, position),
            start_us=start,
            duration_us=duration,
            source_duration_us=int(source.get("duration") or duration),
            speed=_speed_of(draft, segment),
            scale=_scale(segment),
            offset_x=offset_x,
            offset_y=offset_y,
            animation_ids=animations,
        )
        if material.get("type") == "photo":
            qr = spec
        else:
            sticker = spec

    return sticker, qr


def _assign_sfx(tracks: list[dict], sfx_track: int, cut_us: int,
                sticker_start: int | None, qr_start: int | None):
    """Раздаёт три звука по якорям: стык, стикер, QR."""
    segments = _segments(tracks[sfx_track])
    available = list(range(len(segments)))

    def closest(anchor: int | None) -> SegRef | None:
        if anchor is None or not available:
            return None
        best = min(available, key=lambda i: abs(_target(segments[i])[0] - anchor))
        available.remove(best)
        return SegRef(sfx_track, best)

    # Порядок важен: сначала самые надёжные якоря.
    swoosh = closest(cut_us)
    sticker_sfx = closest(sticker_start)
    qr_sfx = closest(qr_start)
    return swoosh, sticker_sfx, qr_sfx


def _subtitles(draft: Draft, tracks: list[dict], sticker_tracks: list[int]):
    """Находит дорожку субтитров и запоминает оформление первого из них."""
    for track_index in sticker_tracks:
        segments = _segments(tracks[track_index])
        if not segments:
            continue
        index = draft.material_index()
        first = segments[0]
        material = index.get(first.get("material_id"), (None, {}))[1]
        if material.get("type") != "text_template_subtitle":
            continue

        resources = material.get("text_info_resources") or []
        text_id = resources[0].get("text_material_id") if resources else None
        animation_id = None
        if resources:
            refs = resources[0].get("extra_material_refs") or []
            animation_id = refs[0] if refs else None

        metrics: list[tuple[int, float, float]] = []
        texts_by_id = {t["id"]: t for t in draft.materials.get("texts", []) or []}
        for segment in segments:
            template = index.get(segment.get("material_id"), (None, {}))[1]
            for resource in template.get("text_info_resources") or []:
                text = texts_by_id.get(resource.get("text_material_id"))
                attach = resource.get("attach_info") or {}
                if not text:
                    continue
                try:
                    import json as _json

                    body = _json.loads(text.get("content") or "{}").get("text") or ""
                except ValueError:
                    body = ""
                metrics.append((
                    len(body),
                    float(attach.get("original_size_width") or 0.0),
                    float(attach.get("original_size_height") or 0.0),
                ))

        offset_x, offset_y = _transform(first)
        style = SubtitleStyle(
            track=track_index,
            template_material_id=first.get("material_id", ""),
            text_material_id=text_id or "",
            animation_id=animation_id,
            scale=_scale(first),
            offset_x=offset_x,
            offset_y=offset_y,
            render_index=int(first.get("render_index") or 14000),
            metrics=metrics,
        )
        return style, len(segments)

    return None, 0
