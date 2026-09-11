"""Статистика: просмотры в сутки, группы и честное количество роликов.

Считать просто просмотры нельзя: ролик, который дольше лежит, обгонит свежий
просто по возрасту, и статистика будет мерить не признаки ролика, а то, какой
из них раньше выложили.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from videobot import stats


def _row(views: int, *, days: float = 1.0, background: str = "blur",
         voice: str = "обыч", music: bool = True,
         duration: float = 14.0, qr: float = 2.5, owner: int = 500) -> dict:
    taken = datetime.now(timezone.utc) - timedelta(days=days)
    return {
        "id": 1, "owner_id": owner, "background": background, "voice_folder": voice,
        "music": int(music), "duration_s": duration, "qr_s": qr,
        "taken_at": taken.isoformat(timespec="seconds"),
        "measured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "views": views,
    }


def test_five_thousand_in_a_day_beats_ten_thousand_in_a_week():
    """Ровно то, ради чего в метрике вообще появилось время."""
    fast = stats.per_day(_row(5000, days=1))
    slow = stats.per_day(_row(10000, days=7))

    assert fast > slow


def test_views_are_divided_by_the_days_lived():
    assert stats.per_day(_row(7000, days=7)) == 1000


def test_video_younger_than_a_day_counts_as_a_day():
    """Замер через час после скачивания иначе дал бы двадцатичетырёхкратное число."""
    assert stats.per_day(_row(100, days=1 / 24)) == 100


def test_numbers_are_grouped_and_not_taken_one_by_one():
    """Среднее «по длительности» без групп — это среднее по одному ролику."""
    assert stats.bucket(14.3, 2.0)[1] == "14–16 с"
    assert stats.bucket(15.9, 2.0)[1] == "14–16 с"
    assert stats.bucket(16.1, 2.0)[1] == "16–18 с"


def test_report_counts_videos_in_every_group():
    """Без количества среднее по трём роликам выглядит как вывод."""
    rows = [_row(1000, background="black"), _row(3000, background="black"),
            _row(2000, background="blur")]
    sections = {section.title: section for section in stats.report(rows)}

    groups = {group.label: group for group in sections["Фон"].groups}
    assert groups["чёрный"].count == 2
    assert groups["размытый"].count == 1
    assert groups["чёрный"].per_day == 2000


def test_every_feature_gets_its_own_section():
    sections = [section.title for section in stats.report([_row(1000)])]

    assert sections == ["Фон", "Папка озвучки", "Фоновая музыка",
                        "Длительность ролика", "Длительность QR"]


def test_voice_folder_is_shown_as_it_is_named_on_disk():
    """Появится третья папка — она сама себя назовёт, без правок в коде."""
    rows = [_row(1000, voice="обыч"), _row(2000, voice="эксперимент")]
    section = next(item for item in stats.report(rows) if item.title == "Папка озвучки")

    assert sorted(group.label for group in section.groups) == ["обыч", "эксперимент"]


def test_description_warns_when_a_group_is_too_thin():
    """На трёх роликах разница — случайность, и об этом надо сказать прямо."""
    rows = [_row(1000, background="black")] + [_row(2000, background="blur")] * 6
    text = stats.describe(stats.report(rows), total=len(rows), skipped=0)

    assert "меньше пяти" in text


def test_description_says_when_there_is_nothing_to_count():
    text = stats.describe(stats.report([]), total=0, skipped=12)

    assert "не по чему считать" in text


def test_description_mentions_videos_left_out():
    rows = [_row(1000)] * 5
    text = stats.describe(stats.report(rows), total=len(rows), skipped=9)

    assert "Без просмотров, не в счёт: 9" in text
