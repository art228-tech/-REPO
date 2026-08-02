"""Живой прогресс в одном сообщении, с троттлингом правок."""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections import deque
from datetime import UTC, datetime

from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.types import Message

MIN_EDIT_INTERVAL = 3.0
TAIL_LINES = 8


class ProgressReporter:
    """Копит строки прогресса и редактирует одно сообщение, а не спамит новыми.

    Кроме списка событий держит отдельную нижнюю строку состояния: она
    заменяется, а не добавляется. Без неё на крупном чате сообщение часами не
    менялось, и со стороны это выглядело как зависший обход.

    Правки чаще раза в несколько секунд Telegram отклоняет, поэтому между
    ними выдерживается интервал.
    """

    def __init__(self, message: Message, header: str = "<b>Обход</b>") -> None:
        self._message = message
        self._header = header
        self._lines: deque[str] = deque(maxlen=TAIL_LINES)
        self._status: str | None = None
        self._last_edit = 0.0
        self._pending = False
        self._lock = asyncio.Lock()

    async def __call__(self, text: str) -> None:
        self._lines.append(text)
        self._pending = True
        await self._maybe_flush()

    async def status(self, text: str) -> None:
        """Обновить нижнюю строку состояния."""
        stamp = datetime.now(UTC).astimezone().strftime("%H:%M:%S")
        self._status = f"⏳ {text} · {stamp}"
        self._pending = True
        await self._maybe_flush()

    async def _maybe_flush(self) -> None:
        if time.monotonic() - self._last_edit >= MIN_EDIT_INTERVAL:
            await self.flush()

    def _render(self) -> str:
        parts = [self._header, ""]
        parts.extend(self._lines)
        if self._status:
            parts.append("")
            parts.append(self._status)
        return "\n".join(parts)

    async def flush(self) -> None:
        async with self._lock:
            if not self._pending:
                return
            self._pending = False
            self._last_edit = time.monotonic()
            try:
                await self._message.edit_text(self._render())
            except TelegramRetryAfter as exc:
                self._last_edit = time.monotonic() + exc.retry_after
            except TelegramBadRequest:
                # «message is not modified» и подобное — не повод падать.
                pass

    async def finish(self, text: str) -> None:
        self._status = None
        self._lines.clear()
        self._lines.append(text)
        self._pending = True
        with contextlib.suppress(TelegramBadRequest, TelegramRetryAfter):
            await self._message.edit_text(text)
