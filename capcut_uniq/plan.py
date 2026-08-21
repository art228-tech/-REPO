"""Расчёт раскладки ролика.

Всё считается от озвучки: её длина задаёт длину ролика, конец её первого
предложения задаёт стык между коротким и длинным фрагментами. Дальше
расставляются акценты и применяются случайные отклонения в заданных границах.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from pathlib import Path

from .asr import Transcript, pick_cut_point
from .config import Config
from .errors import ClipTooShort, PipelineError
from .logging_setup import get_logger
from .profile import SegRef, TemplateProfile
from .units import fmt, s2us, us2s

log = get_logger("plan")

# Минимальный зазор между соседними звуками на одной дорожке.
SFX_GAP_US = 20_000


@dataclass
class SfxPlacement:
    ref: SegRef
    start_us: int
    duration_us: int
    volume: float | None = None
    """None означает «оставить громкость шаблона» — так стоит у свуша."""


@dataclass
class DecorPlacement:
    ref: SegRef
    start_us: int
    duration_us: int
    source_duration_us: int
    speed: float
    offset_y: float
    animation_ids: list[str] = field(default_factory=list)
    sfx: SfxPlacement | None = None


@dataclass
class MusicPlacement:
    ref: SegRef
    duration_us: int
    source_start_us: int
    volume: float


@dataclass
class Cue:
    """Один субтитр: текст, время на таймлайне и слова внутри."""

    text: str
    start_us: int
    duration_us: int
    words: list[tuple[str, int, int]]
    """Тройки (слово, начало в мс от старта субтитра, конец в мс)."""


@dataclass
class RenderPlan:
    profile: TemplateProfile
    total_us: int
    cut_us: int
    cut_reason: str

    voice_path: Path
    voice_start_us: int
    voice_duration_us: int
    voice_trimmed_us: int

    clips: list[Path]
    slot_durations: list[int]
    slot_speeds: list[float]
    overlay_scales: list[float]

    swoosh: SfxPlacement | None = None
    sticker: DecorPlacement | None = None
    qr: DecorPlacement | None = None
    music: MusicPlacement | None = None
    cues: list[Cue] = field(default_factory=list)

    notes: list[str] = field(default_factory=list)

    def describe(self) -> str:
        lines = [
            f"итог {fmt(self.total_us)}; стык {fmt(self.cut_us)} ({self.cut_reason})",
            f"озвучка {self.voice_path.name}: {fmt(self.voice_duration_us)}"
            + (f", обрезан хвост {fmt(self.voice_trimmed_us)}" if self.voice_trimmed_us else ""),
            f"слот 1 {fmt(self.slot_durations[0])} ← {self.clips[0].name}",
            f"слот 2 {fmt(self.slot_durations[1])} ← {self.clips[1].name}",
            f"наложение x{self.overlay_scales[0]:.4f} и x{self.overlay_scales[1]:.4f}",
        ]
        if self.swoosh:
            lines.append(f"свуш на {fmt(self.swoosh.start_us)}")
        if self.sticker:
            lines.append(
                f"стикер {fmt(self.sticker.start_us)}–{fmt(self.sticker.start_us + self.sticker.duration_us)}, "
                f"скорость {self.sticker.speed:.3f}, вертикаль {self.sticker.offset_y:+.4f}"
                + (f", звук {self.sticker.sfx.volume:.3f}" if self.sticker.sfx else "")
            )
        if self.qr:
            lines.append(
                f"QR {fmt(self.qr.start_us)}–{fmt(self.qr.start_us + self.qr.duration_us)}, "
                f"вертикаль {self.qr.offset_y:+.4f}"
                + (f", звук {self.qr.sfx.volume:.3f}" if self.qr.sfx else "")
            )
        if self.music:
            lines.append(f"музыка {fmt(self.music.duration_us)}, громкость {self.music.volume:.3f}")
        if self.cues:
            lines.append(f"субтитров: {len(self.cues)}")
        for note in self.notes:
            lines.append(f"! {note}")
        return "\n".join("   " + line for line in lines)


def voice_usable_duration(total_s: float, trailing_silence_s: float, keep_s: float) -> tuple[float, float]:
    """Сколько озвучки берём и сколько хвоста отрезали."""
    if trailing_silence_s <= keep_s:
        return total_s, 0.0
    trimmed = trailing_silence_s - keep_s
    return max(0.1, total_s - trimmed), trimmed


@dataclass
class Timeline:
    """Раскладка по времени. Считается до выбора клипов, потому что зависит
    только от озвучки — а уже по ней подбираются клипы нужной длины."""

    total_us: int
    cut_us: int
    cut_reason: str
    voice_start_us: int
    voice_duration_us: int
    voice_trimmed_us: int
    slot_durations: list[int]


def timeline(
    profile: TemplateProfile,
    config: Config,
    transcript: Transcript,
    trailing_silence_s: float,
) -> Timeline:
    timing = config.timing
    used_s, trimmed_s = voice_usable_duration(
        transcript.duration, trailing_silence_s, timing.vo_tail_silence_s
    )
    voice_start = profile.voice_start_us
    voice_duration = s2us(used_s)
    total = voice_start + voice_duration + profile.tail_after_voice_us

    lower = max(timing.cut_min_s, us2s(voice_start) + 0.2)
    upper = min(timing.cut_max_s, us2s(total) - 1.0)
    if upper <= lower:
        upper = lower + 0.2

    cut_s, cut_reason = pick_cut_point(transcript, lower - us2s(voice_start), upper - us2s(voice_start))
    cut = voice_start + s2us(cut_s)
    cut = max(s2us(lower), min(cut, s2us(upper)))

    slots = [cut, total - cut]
    if slots[1] <= 0:
        raise PipelineError("Озвучка слишком короткая: на второй фрагмент не остаётся времени")

    return Timeline(
        total_us=total,
        cut_us=cut,
        cut_reason=cut_reason,
        voice_start_us=voice_start,
        voice_duration_us=voice_duration,
        voice_trimmed_us=s2us(trimmed_s),
        slot_durations=slots,
    )


def build(
    profile: TemplateProfile,
    config: Config,
    line: Timeline,
    voice_path: Path,
    clips: list[Path],
    clip_durations: list[float],
    rng: random.Random,
) -> RenderPlan:
    ranges = config.ranges
    notes: list[str] = []
    total = line.total_us
    cut = line.cut_us
    slot_durations = list(line.slot_durations)

    # Клип чуть короче слота закрываем замедлением, а не отказом: нарезка даёт
    # файлы ровно по 15.00с, а слот запросто выходит 15.15с.
    slot_speeds = [1.0, 1.0]
    for index, (clip, available) in enumerate(zip(clips, clip_durations)):
        needed = us2s(slot_durations[index])
        if available + 1e-3 >= needed:
            continue

        floor = needed / (1.0 + config.timing.max_clip_stretch)
        if available + 1e-3 < floor:
            raise ClipTooShort(
                f"Клип {clip.name} длится {available:.2f}с, а в слот {index + 1} нужно "
                f"{needed:.2f}с — не хватает {needed - available:.2f}с, это больше "
                f"допустимого замедления {config.timing.max_clip_stretch * 100:.0f}%"
            )

        slot_speeds[index] = available / needed
        notes.append(
            f"слот {index + 1}: клип короче на {needed - available:.2f}с, "
            f"замедлен на {(1.0 - slot_speeds[index]) * 100:.1f}%"
        )

    overlay_scales = [
        slot.overlay_scale * rng.uniform(1 - ranges.overlay_scale_jitter, 1 + ranges.overlay_scale_jitter)
        for slot in profile.slots
    ]

    # Порядок важен: свуш привязан к стыку, QR — к концу, а стикер ставится
    # между ними и не должен налезть ни на тот, ни на другой.
    swoosh = _plan_swoosh(profile, cut, total)
    qr = _plan_qr(profile, ranges, rng, total)
    sticker = _plan_sticker(profile, ranges, rng, total, swoosh, qr, notes)
    music = _plan_music(profile, ranges, rng, total)

    plan = RenderPlan(
        profile=profile,
        total_us=total,
        cut_us=cut,
        cut_reason=line.cut_reason,
        voice_path=voice_path,
        voice_start_us=line.voice_start_us,
        voice_duration_us=line.voice_duration_us,
        voice_trimmed_us=line.voice_trimmed_us,
        clips=list(clips),
        slot_durations=slot_durations,
        slot_speeds=slot_speeds,
        overlay_scales=overlay_scales,
        swoosh=swoosh,
        sticker=sticker,
        qr=qr,
        music=music,
        notes=notes,
    )
    _resolve_sfx_overlaps(plan, notes)
    return plan


def _plan_qr(profile: TemplateProfile, ranges, rng: random.Random, total: int) -> DecorPlacement | None:
    if not profile.qr:
        return None

    duration = profile.qr.duration_us
    before_end = rng.uniform(*ranges.qr_before_end_s)
    start = total - s2us(before_end)
    start = max(0, min(start, total - duration))

    placement = DecorPlacement(
        ref=profile.qr.segment,
        start_us=start,
        duration_us=min(duration, total - start),
        source_duration_us=profile.qr.source_duration_us,
        speed=profile.qr.speed,
        offset_y=profile.qr.offset_y + rng.uniform(-ranges.qr_dy, ranges.qr_dy),
        animation_ids=list(profile.qr.animation_ids),
    )
    if profile.qr.sfx is not None:
        sfx_start = max(0, placement.start_us + profile.qr.sfx_offset_us)
        placement.sfx = SfxPlacement(
            ref=profile.qr.sfx,
            start_us=sfx_start,
            duration_us=max(1, min(profile.qr.sfx_duration_us, total - sfx_start)),
            volume=_jitter(profile.qr.sfx_volume, ranges.sfx_volume_jitter, rng),
        )
    return placement


def _plan_sticker(profile: TemplateProfile, ranges, rng: random.Random, total: int,
                  swoosh: SfxPlacement | None, qr: DecorPlacement | None,
                  notes: list[str]) -> DecorPlacement | None:
    if not profile.sticker:
        return None

    speed = rng.uniform(*ranges.sticker_speed)
    duration = int(round(profile.sticker.source_duration_us / speed))

    latest = total - duration
    if qr is not None:
        latest = min(latest, qr.start_us - SFX_GAP_US - duration)

    low, high = ranges.sticker_start_s
    earliest = s2us(low)
    if swoosh is not None and profile.sticker.sfx is not None:
        # Звук стикера едет вместе с ним и не должен наехать на свуш.
        earliest = max(earliest, swoosh.start_us + swoosh.duration_us + SFX_GAP_US
                       - profile.sticker.sfx_offset_us)

    start = s2us(rng.uniform(low, high))
    if start < earliest:
        start = earliest
    if start > latest:
        start = max(0, latest)
        notes.append(
            f"стикер не помещался в {low:g}–{high:g}с, сдвинут на {fmt(start)} — ролик слишком короткий"
        )

    placement = DecorPlacement(
        ref=profile.sticker.segment,
        start_us=start,
        duration_us=duration,
        source_duration_us=profile.sticker.source_duration_us,
        speed=speed,
        offset_y=profile.sticker.offset_y + rng.uniform(-ranges.sticker_dy, ranges.sticker_dy),
        animation_ids=list(profile.sticker.animation_ids),
    )
    if profile.sticker.sfx is not None:
        sfx_start = max(0, placement.start_us + profile.sticker.sfx_offset_us)
        placement.sfx = SfxPlacement(
            ref=profile.sticker.sfx,
            start_us=sfx_start,
            duration_us=max(1, min(profile.sticker.sfx_duration_us, total - sfx_start)),
            volume=_jitter(profile.sticker.sfx_volume, ranges.sfx_volume_jitter, rng),
        )
    return placement


def _plan_swoosh(profile: TemplateProfile, cut: int, total: int) -> SfxPlacement | None:
    if profile.swoosh is None:
        return None
    start = max(0, cut + profile.swoosh_offset_us)
    duration = max(1, min(profile.swoosh_duration_us, total - start))
    return SfxPlacement(ref=profile.swoosh, start_us=start, duration_us=duration, volume=None)


def _plan_music(profile: TemplateProfile, ranges, rng: random.Random, total: int) -> MusicPlacement | None:
    if profile.music is None:
        return None
    duration = max(1, total - profile.music_tail_us)
    return MusicPlacement(
        ref=profile.music,
        duration_us=duration,
        source_start_us=profile.music_source_start_us,
        volume=rng.uniform(*ranges.music_volume),
    )


def _jitter(value: float, fraction: float, rng: random.Random) -> float:
    return max(0.0, min(1.0, value * rng.uniform(1 - fraction, 1 + fraction)))


def _resolve_sfx_overlaps(plan: RenderPlan, notes: list[str]) -> None:
    """На одной дорожке сегменты пересекаться не могут — подрезаем более ранний."""
    items = [item for item in (plan.swoosh,
                               plan.sticker.sfx if plan.sticker else None,
                               plan.qr.sfx if plan.qr else None) if item]
    same_track: dict[int, list[SfxPlacement]] = {}
    for item in items:
        same_track.setdefault(item.ref.track, []).append(item)

    for placements in same_track.values():
        placements.sort(key=lambda p: p.start_us)
        for earlier, later in zip(placements, placements[1:]):
            limit = later.start_us - SFX_GAP_US
            if earlier.start_us + earlier.duration_us > limit:
                new_duration = max(1, limit - earlier.start_us)
                notes.append(
                    f"звук на {fmt(earlier.start_us)} подрезан с {fmt(earlier.duration_us)} "
                    f"до {fmt(new_duration)}, иначе наехал бы на следующий"
                )
                earlier.duration_us = new_duration
