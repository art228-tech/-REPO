"""Расчёт таймлайна и правила выбора точки стыка."""
from __future__ import annotations

import random
from pathlib import Path

import pytest

from capcut_uniq import plan as plan_module, profile as profile_module
from capcut_uniq.asr import Transcript, Word, pick_cut_point
from capcut_uniq.config import Config
from capcut_uniq.plan import voice_usable_duration
from capcut_uniq.units import us2s


def words(pairs):
    return [Word(text=text, start=start, end=end) for text, start, end in pairs]


def test_trailing_silence_trimmed():
    used, trimmed = voice_usable_duration(total_s=14.0, trailing_silence_s=0.5, keep_s=0.1)
    assert round(used, 3) == 13.6
    assert round(trimmed, 3) == 0.4


def test_abrupt_ending_left_alone():
    """Если запись обрывается на звуке, удлинять нечем — берём как есть."""
    used, trimmed = voice_usable_duration(total_s=14.0, trailing_silence_s=0.02, keep_s=0.1)
    assert used == 14.0
    assert trimmed == 0.0


def test_cut_at_sentence_end():
    transcript = Transcript(duration=10.0, words=words([
        ("первое", 0.0, 1.0), ("предложение.", 1.1, 2.6),
        ("второе", 3.0, 3.6), ("пошло", 3.7, 4.4),
    ]))
    cut, reason = pick_cut_point(transcript, 1.5, 4.0)
    assert cut == 2.6
    assert "первого предложения" in reason


def test_cut_stretched_to_lower_bound():
    transcript = Transcript(duration=10.0, words=words([
        ("да.", 0.0, 0.6), ("дальше", 1.0, 1.8), ("речь", 1.9, 2.4),
    ]))
    cut, reason = pick_cut_point(transcript, 1.5, 4.0)
    assert cut == 1.5
    assert "нижнего предела" in reason


def test_cut_falls_back_to_pause_inside_sentence():
    """Первое предложение затянулось — ищем паузу внутри коридора."""
    transcript = Transcript(duration=12.0, words=words([
        ("очень", 0.0, 0.8), ("длинное", 0.9, 1.6),
        ("вступление", 2.2, 3.1),
        ("которое", 3.2, 3.8), ("никак", 3.9, 4.5), ("не", 4.6, 4.8),
        ("кончается.", 4.9, 6.0),
    ]))
    cut, reason = pick_cut_point(transcript, 1.5, 4.0)
    assert cut == pytest.approx(1.6)
    assert "пауз" in reason


def test_timeline_uses_voice_length(template_folder: Path):
    profile = profile_module.analyse(template_folder)
    config = Config(clips_dir=Path("."), voice_dir=Path("."))
    transcript = Transcript(duration=10.0, words=words([
        ("первое", 0.0, 1.0), ("предложение.", 1.1, 2.0), ("дальше", 2.4, 3.0),
    ]))

    line = plan_module.timeline(profile, config, transcript, trailing_silence_s=0.0)

    # Ролик = озвучка плюс хвост из шаблона, слоты в сумме дают всю длину.
    assert line.voice_duration_us == 10_000_000
    assert line.total_us == line.voice_start_us + 10_000_000 + profile.tail_after_voice_us
    assert sum(line.slot_durations) == line.total_us
    assert line.cut_us == line.voice_start_us + 2_000_000


def test_randomization_within_ranges(template_folder: Path):
    profile = profile_module.analyse(template_folder)
    config = Config(clips_dir=Path("."), voice_dir=Path("."))
    transcript = Transcript(duration=13.0, words=words([
        ("первое", 0.0, 1.0), ("предложение.", 1.1, 2.2), ("дальше", 2.6, 3.2),
    ]))
    line = plan_module.timeline(profile, config, transcript, trailing_silence_s=0.0)

    for seed in range(25):
        built = plan_module.build(
            profile, config, line, Path("voice.mp3"),
            [Path("a.mp4"), Path("b.mp4")], [30.0, 30.0], random.Random(seed),
        )

        start = us2s(built.sticker.start_us)
        assert 4.0 - 1e-6 <= start <= 8.0 + 1e-6
        assert 1.2 <= built.sticker.speed <= 1.4
        assert abs(built.sticker.offset_y - profile.sticker.offset_y) <= 0.03 + 1e-9
        assert 0.05 <= built.music.volume <= 0.08

        before_end = us2s(built.total_us - built.qr.start_us)
        assert 1.0 - 1e-6 <= before_end <= 2.0 + 1e-6
        assert abs(built.qr.offset_y - profile.qr.offset_y) <= 0.03 + 1e-9

        for index, scale in enumerate(built.overlay_scales):
            base = profile.slots[index].overlay_scale
            assert abs(scale - base) <= base * 0.05 + 1e-9

        volume = built.sticker.sfx.volume
        assert abs(volume - profile.sticker.sfx_volume) <= profile.sticker.sfx_volume * 0.05 + 1e-9


def test_sticker_duration_follows_speed(template_folder: Path):
    """Длительность сегмента и комбо-анимации завязаны на скорость."""
    profile = profile_module.analyse(template_folder)
    config = Config(clips_dir=Path("."), voice_dir=Path("."))
    transcript = Transcript(duration=13.0, words=words([("фраза.", 0.0, 2.0), ("вторая", 2.4, 3.0)]))
    line = plan_module.timeline(profile, config, transcript, trailing_silence_s=0.0)

    built = plan_module.build(
        profile, config, line, Path("voice.mp3"),
        [Path("a.mp4"), Path("b.mp4")], [30.0, 30.0], random.Random(3),
    )
    expected = round(profile.sticker.source_duration_us / built.sticker.speed)
    assert built.sticker.duration_us == expected


def test_sfx_never_overlap(template_folder: Path):
    profile = profile_module.analyse(template_folder)
    config = Config(clips_dir=Path("."), voice_dir=Path("."))
    transcript = Transcript(duration=11.0, words=words([("фраза.", 0.0, 1.6), ("вторая", 2.0, 2.6)]))
    line = plan_module.timeline(profile, config, transcript, trailing_silence_s=0.0)

    for seed in range(40):
        built = plan_module.build(
            profile, config, line, Path("voice.mp3"),
            [Path("a.mp4"), Path("b.mp4")], [30.0, 30.0], random.Random(seed),
        )
        placements = sorted(
            [item for item in (built.swoosh, built.sticker.sfx, built.qr.sfx) if item],
            key=lambda item: item.start_us,
        )
        for earlier, later in zip(placements, placements[1:]):
            assert earlier.start_us + earlier.duration_us <= later.start_us


def test_clip_shorter_than_slot_is_rejected(template_folder: Path):
    from capcut_uniq.errors import ClipTooShort

    profile = profile_module.analyse(template_folder)
    config = Config(clips_dir=Path("."), voice_dir=Path("."))
    transcript = Transcript(duration=13.0, words=words([("фраза.", 0.0, 2.0), ("вторая", 2.4, 3.0)]))
    line = plan_module.timeline(profile, config, transcript, trailing_silence_s=0.0)

    with pytest.raises(ClipTooShort):
        plan_module.build(
            profile, config, line, Path("voice.mp3"),
            [Path("a.mp4"), Path("b.mp4")], [30.0, 2.0], random.Random(1),
        )
