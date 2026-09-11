"""Заливка ролика в Telegram и напоминания про просмотры.

Оба места разговаривают с Telegram, поэтому проверяются на подставном боте:
важно не то, что Telegram ответит, а что программа сделает с его ответом.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

from conftest import video_data

from videobot import uploader
from videobot.tg import reminders


class _Document:
    def __init__(self, file_id: str):
        self.file_id = file_id


class _Message:
    def __init__(self, file_id: str):
        self.document = _Document(file_id)
        self.video = None
        self.message_id = 777


class _Bot:
    """Подставной бот: запоминает, что у него просили."""

    def __init__(self, fail: Exception | None = None):
        self.sent: list[dict] = []
        self.messages: list[tuple[int, str]] = []
        self.deleted: list[int] = []
        self.fail = fail

    async def send_document(self, **kwargs):
        if self.fail is not None:
            raise self.fail
        self.sent.append(kwargs)
        return _Message(f"file-{len(self.sent)}")

    async def send_message(self, chat_id, text, **kwargs):
        self.messages.append((chat_id, text))

    async def delete_message(self, chat_id, message_id):
        self.deleted.append(message_id)


def _queued(base, tmp_path: Path, name: str = "ролик") -> tuple:
    path = tmp_path / f"{name}.mp4"
    path.write_bytes(b"\x00" * 1024)
    base.add_video(name, str(path), video_data())
    return base.next_pending(), path


def test_uploaded_video_keeps_only_its_telegram_id(base, tmp_path: Path):
    """Файл больше не нужен: дальше ролик живёт идентификатором Telegram."""
    row, _ = _queued(base, tmp_path)
    bot = _Bot()

    assert asyncio.run(uploader.upload_one(bot, base, row, chat_id=42)) is True

    saved = base.video(row["id"])
    assert saved["file_id"] == "file-1"
    assert saved["file_path"] == ""
    assert saved["status"] == "ready"


def test_storage_message_is_removed_from_the_chat(base, tmp_path: Path):
    """Идентификатор уже получен, а чат админа не надо заваливать файлами."""
    row, _ = _queued(base, tmp_path)
    bot = _Bot()
    asyncio.run(uploader.upload_one(bot, base, row, chat_id=42))

    assert bot.deleted == [777]


def test_missing_file_is_named_in_the_error(base, tmp_path: Path):
    row, path = _queued(base, tmp_path)
    path.unlink()
    bot = _Bot()

    assert asyncio.run(uploader.upload_one(bot, base, row, chat_id=42)) is False
    assert "не найден" in base.video(row["id"])["error"]
    assert base.counts()["failed"] == 1


def test_too_heavy_file_is_refused_before_telegram_says_no(base, tmp_path: Path):
    """Так человек видит, какой ролик тяжёлый, а не невнятный отказ Telegram."""
    row, path = _queued(base, tmp_path)
    path.write_bytes(b"\x00" * (uploader.MAX_BYTES + 1))
    bot = _Bot()

    assert asyncio.run(uploader.upload_one(bot, base, row, chat_id=42)) is False
    assert not bot.sent
    assert "50 МБ" in base.video(row["id"])["error"]


def test_reminder_lists_all_of_a_persons_videos_in_one_message(base, tmp_path: Path):
    """Пять напоминаний подряд — это спам, одно письмо со списком — нет."""
    for name in ("первый", "второй"):
        row, _ = _queued(base, tmp_path, name)
        base.mark_ready(row["id"], f"file-{name}")
    base.assign(500, 2)
    _take_long_ago(base, [1, 2])

    bot = _Bot()
    asyncio.run(reminders.send_due(bot, base, hours=24))

    assert len(bot.messages) == 1
    chat_id, text = bot.messages[0]
    assert chat_id == 500
    assert "первый" in text and "второй" in text


def test_reminder_never_comes_a_second_time(base, tmp_path: Path):
    row, _ = _queued(base, tmp_path)
    base.mark_ready(row["id"], "file-1")
    base.assign(500, 1)
    _take_long_ago(base, [row["id"]])

    bot = _Bot()
    asyncio.run(reminders.send_due(bot, base, hours=24))
    asyncio.run(reminders.send_due(bot, base, hours=24))

    assert len(bot.messages) == 1


def test_blocked_person_does_not_hold_the_queue_forever(base, tmp_path: Path):
    """Человек мог заблокировать бота — упираться в него вечно незачем."""
    row, _ = _queued(base, tmp_path)
    base.mark_ready(row["id"], "file-1")
    base.assign(500, 1)
    _take_long_ago(base, [row["id"]])

    class _Blocked(_Bot):
        async def send_message(self, chat_id, text, **kwargs):
            raise RuntimeError("bot was blocked by the user")

    asyncio.run(reminders.send_due(_Blocked(), base, hours=24))

    assert base.due_for_reminder(24) == []


def _take_long_ago(base, video_ids: list[int]) -> None:
    stamp = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat(timespec="seconds")
    with base.connect() as conn:
        for video_id in video_ids:
            conn.execute("UPDATE videos SET taken_at = ? WHERE id = ?", (stamp, video_id))
