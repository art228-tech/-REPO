"""База: путь ролика от загрузки до просмотров.

Здесь проверяется то, что нельзя увидеть глазами в боте: выдаётся ли по
хронологии, не уходит ли один ролик двоим, что происходит с невыданным при
отзыве доступа.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from conftest import video_data

from videobot.db import READY


def _ready(base, name: str, **kwargs) -> int:
    base.add_video(name, f"D:/{name}.mp4", video_data(**kwargs))
    row = base.next_pending()
    base.mark_ready(row["id"], f"file-{name}")
    return row["id"]


def test_same_video_is_not_taken_twice(base):
    """Имена уникальны, и повторная загрузка — это оплошность, а не новый ролик."""
    assert base.add_video("ролик", "D:/a.mp4", video_data()) is True
    assert base.add_video("ролик", "D:/b.mp4", video_data()) is False


def test_video_data_survives_the_trip_to_the_base(base):
    video_id = _ready(base, "ролик", background="black", voice_folder="необыч",
                      music=False, qr_s=3.0)
    row = base.video(video_id)

    assert row["background"] == "black"
    assert row["voice_folder"] == "необыч"
    assert row["music"] == 0
    assert row["qr_s"] == 3.0


def test_videos_are_handed_over_oldest_first(base):
    for name in ("первый", "второй", "третий"):
        _ready(base, name)
    base.set_access(500, True)
    base.assign(500, 3)

    handed = base.next_to_hand_over(500, 2)
    assert [item.name for item in handed] == ["первый", "второй"]


def test_assigned_video_does_not_go_to_anyone_else(base):
    _ready(base, "ролик")
    assert base.assign(500, 5) == 1
    assert base.assign(600, 5) == 0


def test_taken_video_leaves_the_queue(base):
    _ready(base, "ролик")
    base.assign(500, 1)
    assert base.waiting_for(500) == 1

    base.mark_taken(1)
    assert base.waiting_for(500) == 0


def test_revoking_access_returns_only_what_was_not_taken(base):
    """Скачанное остаётся за человеком: по нему уже есть или будут просмотры."""
    _ready(base, "скачанный")
    _ready(base, "невыданный")
    base.assign(500, 2)
    base.mark_taken(1)

    assert base.take_back(500) == 1
    assert base.counts()["free"] == 1
    assert len(base.history(500)) == 1


def test_views_keep_every_measurement(base):
    """Ролик набирает просмотры со временем, и прежний замер тоже нужен."""
    _ready(base, "ролик")
    base.assign(500, 1)
    base.mark_taken(1)

    base.add_views(1, 1000)
    base.add_views(1, 8000)

    assert base.history(500)[0]["last_views"] == 8000
    assert len(base.measured()) == 1


def test_statistics_take_the_latest_measurement(base):
    _ready(base, "ролик")
    base.assign(500, 1)
    base.mark_taken(1)
    base.add_views(1, 1000)
    base.add_views(1, 8000)

    assert base.measured()[0]["views"] == 8000


def test_video_without_views_stays_out_of_statistics(base):
    _ready(base, "с просмотрами")
    _ready(base, "без просмотров")
    base.assign(500, 2)
    base.mark_taken(1)
    base.mark_taken(2)
    base.add_views(1, 500)

    assert len(base.measured()) == 1


def test_reminder_waits_for_the_day_to_pass(base):
    _ready(base, "ролик")
    base.assign(500, 1)
    base.mark_taken(1)

    assert base.due_for_reminder(24) == []


def test_reminder_comes_due_a_day_after_the_download(base):
    _ready(base, "ролик")
    base.assign(500, 1)
    _take_at(base, 1, hours_ago=25)

    due = base.due_for_reminder(24)
    assert [row["name"] for row in due] == ["ролик"]


def test_reminder_is_sent_once_and_never_again(base):
    """Ролик могли и не выложить — долбить человека каждый день незачем."""
    _ready(base, "ролик")
    base.assign(500, 1)
    _take_at(base, 1, hours_ago=25)

    base.mark_reminded(1)
    assert base.due_for_reminder(24) == []


def test_filled_views_cancel_the_reminder(base):
    _ready(base, "ролик")
    base.assign(500, 1)
    _take_at(base, 1, hours_ago=25)
    base.add_views(1, 1000)

    assert base.due_for_reminder(24) == []


def test_first_admin_gets_access_along_with_the_badge(base):
    base.make_admin(42)
    person = base.person(42)

    assert person["is_admin"] == 1
    assert person["has_access"] == 1
    assert base.admin_ids() == [42]


def test_pressing_start_does_not_grant_access(base):
    """Бота может открыть кто угодно — доступ выдаётся руками."""
    base.remember_person(777, "Чужой")
    assert base.person(777)["has_access"] == 0


def test_counts_tell_free_videos_from_assigned(base):
    _ready(base, "свободный")
    _ready(base, "выданный")
    base.assign(500, 1)

    counts = base.counts()
    assert counts["ready"] == 2
    assert counts["free"] == 1


def _take_at(base, video_id: int, hours_ago: int) -> None:
    """Отматывает время скачивания назад — иначе тест ждал бы сутки."""
    stamp = (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat(timespec="seconds")
    with base.connect() as conn:
        conn.execute("UPDATE videos SET taken_at = ? WHERE id = ?", (stamp, video_id))


def test_failed_upload_is_visible_in_counts(base):
    base.add_video("ролик", "D:/нет.mp4", video_data())
    base.mark_failed(1, "файл не найден")

    assert base.counts()["failed"] == 1
    assert base.counts()["ready"] == 0
    assert base.next_pending() is None


def test_ready_video_carries_its_file_id(base):
    video_id = _ready(base, "ролик")
    row = base.video(video_id)

    assert row["status"] == READY
    assert row["file_id"] == "file-ролик"
    # Путь стирается: файл больше не нужен, ролик живёт в Telegram.
    assert row["file_path"] == ""
