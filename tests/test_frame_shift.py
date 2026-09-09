"""Несколько роликов из одного набора материалов за счёт сдвига кадра вбок.

Клип шире кадра — при масштабе больше единицы его бока обрезаны, и там остаётся
неиспользованная картинка. Сдвиг её открывает: часть прежнего кадра уходит,
столько же приходит с обрезанной стороны.

Сколько роликов делать и насколько сдвигать — настройки: два ролика это только
сдвиги влево и вправо, три — плюс обычный кадр посередине.
"""
from __future__ import annotations

import random
from pathlib import Path

import pytest

from capcut_uniq import builder, plan as plan_module, profile as profile_module
from capcut_uniq.asr import Transcript, Word
from capcut_uniq.batch import frame_shifts, widest_slots
from capcut_uniq.config import DEFAULT_FRAME_SHIFT, Config, parse_shift
from capcut_uniq.draft_io import Draft
from capcut_uniq.errors import PipelineError
from capcut_uniq.ffmpeg import MediaInfo


def _config(**kwargs) -> Config:
    return Config(clips_dir=Path("."), voice_dir=Path("."), **kwargs)


def test_one_frame_by_default():
    assert frame_shifts(_config()) == [0.0]


def test_default_shift_is_a_third():
    """Сдвиг на треть ширины: две трети прежнего кадра остаются на месте."""
    assert DEFAULT_FRAME_SHIFT == pytest.approx(1 / 3)


def test_three_frames_keep_the_plain_one_in_the_middle():
    shifts = frame_shifts(_config(frames_per_set=3))
    assert shifts == pytest.approx([0.0, -1 / 3, 1 / 3])


def test_two_frames_drop_the_plain_one():
    """Середина повторяла бы обычную сборку, поэтому при двух её нет."""
    shifts = frame_shifts(_config(frames_per_set=2))
    assert shifts == pytest.approx([-1 / 3, 1 / 3])
    assert 0.0 not in shifts


def test_shift_size_is_taken_from_the_settings():
    assert frame_shifts(_config(frames_per_set=2, frame_shift=1 / 4)) == pytest.approx([-0.25, 0.25])
    assert frame_shifts(_config(frames_per_set=3, frame_shift=0.1)) == pytest.approx([0.0, -0.1, 0.1])


def test_zero_shift_leaves_a_single_frame():
    """Без сдвига ролики отличались бы только озвучкой — набор незачем дробить."""
    assert frame_shifts(_config(frames_per_set=3, frame_shift=0.0)) == [0.0]


def test_count_is_kept_within_reason():
    assert frame_shifts(_config(frames_per_set=0)) == [0.0]
    assert len(frame_shifts(_config(frames_per_set=9))) == 3


def test_side_of_the_shift_is_not_the_users_business():
    """Знак задаёт программа, поэтому минус в настройке ничего не переворачивает."""
    assert frame_shifts(_config(frames_per_set=2, frame_shift=-1 / 4)) == pytest.approx([-0.25, 0.25])


def test_shift_is_read_as_a_fraction():
    assert parse_shift("1/3") == pytest.approx(1 / 3)
    assert parse_shift("1/4") == pytest.approx(0.25)


def test_shift_is_read_as_a_number_or_percent():
    assert parse_shift("0.25") == pytest.approx(0.25)
    assert parse_shift("0,25") == pytest.approx(0.25)
    assert parse_shift("25%") == pytest.approx(0.25)
    assert parse_shift(1 / 4) == pytest.approx(0.25)


def test_empty_shift_means_the_default():
    assert parse_shift("") == pytest.approx(DEFAULT_FRAME_SHIFT)
    assert parse_shift("   ") == pytest.approx(DEFAULT_FRAME_SHIFT)


def test_nonsense_shift_is_explained_not_swallowed():
    """Опечатку надо поймать до сборки, а не собрать сотню роликов не тем кадром."""
    for value in ("треть", "1/0", "1/3/4", "%"):
        with pytest.raises(PipelineError):
            parse_shift(value)


def test_shift_beyond_half_the_width_is_refused():
    """Столько запаса по бокам не бывает даже у самого широкого клипа."""
    assert parse_shift("1/2") == pytest.approx(0.5)
    with pytest.raises(PipelineError):
        parse_shift("2/3")
    with pytest.raises(PipelineError):
        parse_shift("-1/3")


def _shift(scale: float, share: float, start: float = 0.0):
    clip = {"transform": {"x": start}}
    notes: list[str] = []
    builder._shift_frame(clip, scale, share, position=0, is_overlay=False, notes=notes)
    return clip["transform"]["x"], notes


def test_shift_is_doubled_for_the_draft():
    """В черновике сдвиг записан в долях половины ширины, а не всей."""
    moved, notes = _shift(scale=3.0, share=1 / 3)
    assert moved == pytest.approx(2 / 3)
    assert not notes


def test_left_and_right_are_mirrored():
    left, _ = _shift(scale=3.0, share=-1 / 3)
    right, _ = _shift(scale=3.0, share=1 / 3)
    assert left == pytest.approx(-right)


def test_shift_adds_to_what_the_template_had():
    moved, _ = _shift(scale=3.0, share=1 / 3, start=0.2)
    assert moved == pytest.approx(0.2 + 2 / 3)


def test_shift_stops_at_the_edge_of_the_clip():
    """За краем клипа пустота, поэтому дальше запаса не двигаем."""
    moved, notes = _shift(scale=1.2, share=1 / 3)
    assert moved == pytest.approx(0.2)
    assert notes and "нет запаса" in notes[0]


def test_clip_that_exactly_fills_the_frame_does_not_move():
    moved, notes = _shift(scale=1.0, share=1 / 3)
    assert moved == 0.0
    assert notes


def test_wide_clip_moves_the_whole_way():
    """У фона масштаб около четырёх — запаса вдоволь."""
    moved, notes = _shift(scale=4.0, share=1 / 3)
    assert moved == pytest.approx(2 / 3)
    assert not notes


def test_smaller_shift_needs_less_spare_picture():
    """Ради этого настройка и нужна: где треть упирается в край, четверть ещё влезает.

    Запас по бокам равен «масштаб минус единица», а сдвиг просит вдвое больше
    своей доли. При масштабе 1.5 четверть проходит ровно, а треть урезается.
    """
    quarter, quiet = _shift(scale=1.5, share=1 / 4)
    assert quarter == pytest.approx(0.5)
    assert not quiet

    third, complaint = _shift(scale=1.5, share=1 / 3)
    assert third == pytest.approx(0.5)
    assert complaint and "нет запаса" in complaint[0]


def test_overlay_does_not_add_its_own_note():
    """Про урезанный сдвиг достаточно сказать один раз на слот."""
    clip = {"transform": {"x": 0.0}}
    notes: list[str] = []
    builder._shift_frame(clip, 1.1, 1 / 3, position=0, is_overlay=True, notes=notes)
    assert not notes


def test_missing_transform_is_created():
    clip: dict = {}
    builder._shift_frame(clip, 3.0, 1 / 3, position=0, is_overlay=False, notes=[])
    assert clip["transform"]["x"] == pytest.approx(2 / 3)


def _words(pairs):
    return [Word(text=text, start=start, end=end) for text, start, end in pairs]


def _positions_in_draft(template_folder: Path, config: Config) -> list[float]:
    """Куда встала рамка в каждом ролике набора — по готовому черновику.

    Проверяет всю цепочку, а не отдельную функцию: настройка, раскладка ролика и
    правка черновика. Разъехаться может любое звено.
    """
    profile = profile_module.analyse(template_folder)
    transcript = Transcript(duration=13.0,
                            words=_words([("фраза.", 0.0, 2.0), ("вторая", 2.4, 3.0)]))
    line = plan_module.timeline(profile, config, transcript, trailing_silence_s=0.0)
    # Размеры как у клипа шаблона, чтобы поправка масштаба не вмешалась.
    info = MediaInfo(path=Path("a.mp4"), duration_s=30.0, width=1280, height=576,
                     has_audio=True, has_video=True, fps=60.0)

    found: list[float] = []
    for shift in frame_shifts(config):
        built = plan_module.build(
            profile, config, line, Path("voice.mp3"),
            [Path("a.mp4"), Path("b.mp4")], [30.0, 30.0], random.Random(1),
        )
        built.frame_shift = shift

        draft = Draft.load(template_folder)
        media = {
            f"slot{index}": builder.InstalledMedia(
                material_ids=[], filename="a.mp4", relative="video/a.mp4", info=info)
            for index in range(len(profile.slots))
        }
        builder._apply_slots(draft, profile, built, media, [])

        clip = profile.slots[0].background.get(draft).get("clip") or {}
        found.append((clip.get("transform") or {}).get("x"))
    return found


def test_three_frames_of_a_set_land_at_three_places(template_folder: Path):
    """В черновике сдвиг записан в долях половины ширины, отсюда две трети."""
    positions = _positions_in_draft(template_folder, _config(frames_per_set=3))
    assert positions == pytest.approx([0.0, -2 / 3, 2 / 3])


def test_two_frames_land_only_to_the_sides(template_folder: Path):
    positions = _positions_in_draft(
        template_folder, _config(frames_per_set=2, frame_shift=1 / 4))
    assert positions == pytest.approx([-0.5, 0.5])


def test_overlay_moves_together_with_the_background(template_folder: Path):
    """Иначе резкое наложение осталось бы на месте и сдвиг был бы виден как рассинхрон."""
    profile = profile_module.analyse(template_folder)
    config = _config(frames_per_set=2)
    transcript = Transcript(duration=13.0,
                            words=_words([("фраза.", 0.0, 2.0), ("вторая", 2.4, 3.0)]))
    line = plan_module.timeline(profile, config, transcript, trailing_silence_s=0.0)
    built = plan_module.build(
        profile, config, line, Path("voice.mp3"),
        [Path("a.mp4"), Path("b.mp4")], [30.0, 30.0], random.Random(1),
    )
    built.frame_shift = frame_shifts(config)[1]

    draft = Draft.load(template_folder)
    info = MediaInfo(path=Path("a.mp4"), duration_s=30.0, width=1280, height=576,
                     has_audio=True, has_video=True, fps=60.0)
    media = {
        f"slot{index}": builder.InstalledMedia(
            material_ids=[], filename="a.mp4", relative="video/a.mp4", info=info)
        for index in range(len(profile.slots))
    }
    builder._apply_slots(draft, profile, built, media, [])

    for slot in profile.slots:
        background = ((slot.background.get(draft).get("clip") or {}).get("transform") or {}).get("x")
        overlay = ((slot.overlay.get(draft).get("clip") or {}).get("transform") or {}).get("x")
        assert background == pytest.approx(2 / 3)
        assert overlay == pytest.approx(2 / 3)


class _Line:
    def __init__(self, short: int, long: int):
        self.slot_durations = [short, long]


def test_clips_are_chosen_for_the_longest_voice():
    """Клипы у набора общие, а озвучки разной длины — берём под самую длинную."""
    lines = [_Line(2_000_000, 9_000_000),
             _Line(3_500_000, 7_000_000),
             _Line(2_800_000, 12_000_000)]
    assert widest_slots(lines) == [3_500_000, 12_000_000]


def test_single_voice_asks_for_its_own_slots():
    assert widest_slots([_Line(2_000_000, 9_000_000)]) == [2_000_000, 9_000_000]


def test_no_voices_is_an_error():
    from capcut_uniq.errors import PipelineError

    with pytest.raises(PipelineError):
        widest_slots([])
