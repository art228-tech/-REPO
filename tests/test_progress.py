"""Отрисовка прогресса в одном сообщении."""

from __future__ import annotations

import pytest
from aiogram.exceptions import TelegramBadRequest

from tgparser.bot.progress import ProgressReporter


class FakeMessage:
    def __init__(self, fail_with: Exception | None = None) -> None:
        self.texts: list[str] = []
        self.fail_with = fail_with

    async def edit_text(self, text: str, **kwargs) -> None:
        if self.fail_with is not None:
            raise self.fail_with
        self.texts.append(text)

    @property
    def last(self) -> str:
        return self.texts[-1] if self.texts else ""


@pytest.fixture
def message() -> FakeMessage:
    return FakeMessage()


@pytest.fixture
def reporter(message: FakeMessage) -> ProgressReporter:
    return ProgressReporter(message, "<b>Обход</b>")


def unthrottle(reporter: ProgressReporter) -> None:
    """Сбросить троттлинг, чтобы следующая правка ушла сразу."""
    reporter._last_edit = 0.0


class TestEventLines:
    async def test_first_line_is_shown(self, reporter, message):
        await reporter("Найдено чатов: 27")
        assert "Найдено чатов: 27" in message.last
        assert "<b>Обход</b>" in message.last

    async def test_lines_accumulate(self, reporter, message):
        await reporter("первая")
        unthrottle(reporter)
        await reporter("вторая")
        assert "первая" in message.last
        assert "вторая" in message.last

    async def test_only_the_tail_is_kept(self, reporter, message):
        for index in range(20):
            unthrottle(reporter)
            await reporter(f"строка {index}")
        assert "строка 19" in message.last
        assert "строка 0" not in message.last


class TestStatusLine:
    async def test_status_is_rendered(self, reporter, message):
        await reporter.status("[1/27] Чат · сообщений 100")
        assert "сообщений 100" in message.last
        assert "⏳" in message.last

    async def test_status_replaces_itself(self, reporter, message):
        await reporter.status("сообщений 100")
        unthrottle(reporter)
        await reporter.status("сообщений 200")
        assert "сообщений 200" in message.last
        assert "сообщений 100" not in message.last

    async def test_status_has_a_timestamp(self, reporter, message):
        """По времени видно, что обход жив, а не завис."""
        import re

        await reporter.status("идёт")
        assert re.search(r"\d\d:\d\d:\d\d", message.last)

    async def test_status_sits_below_events(self, reporter, message):
        await reporter("событие")
        unthrottle(reporter)
        await reporter.status("состояние")
        body = message.last
        assert body.index("событие") < body.index("состояние")

    async def test_events_and_status_coexist(self, reporter, message):
        await reporter.status("состояние")
        unthrottle(reporter)
        await reporter("новое событие")
        assert "состояние" in message.last
        assert "новое событие" in message.last


class TestThrottling:
    async def test_rapid_updates_are_collapsed(self, reporter, message):
        await reporter("первая")
        for index in range(10):
            await reporter.status(f"шаг {index}")
        # Первая правка ушла, остальные придержаны интервалом.
        assert len(message.texts) == 1

    async def test_flush_sends_pending_state(self, reporter, message):
        await reporter("первая")
        await reporter.status("накопленное")
        assert "накопленное" not in message.last

        unthrottle(reporter)
        await reporter.flush()
        assert "накопленное" in message.last

    async def test_flush_without_changes_is_noop(self, reporter, message):
        await reporter("первая")
        count = len(message.texts)
        unthrottle(reporter)
        await reporter.flush()
        assert len(message.texts) == count


class TestFinish:
    async def test_finish_replaces_everything(self, reporter, message):
        await reporter("событие")
        unthrottle(reporter)
        await reporter.status("состояние")
        unthrottle(reporter)
        await reporter.finish("Обход завершён")
        assert message.last == "Обход завершён"


class TestFailures:
    async def test_telegram_rejection_does_not_raise(self):
        message = FakeMessage(
            fail_with=TelegramBadRequest(method=None, message="message is not modified")
        )
        reporter = ProgressReporter(message)
        await reporter("что-то")
        await reporter.status("что-то ещё")
