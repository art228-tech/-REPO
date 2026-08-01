"""Живой прогресс в одном сообщении, с троттлингом правок."""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections import deque

from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.types import Message

MIN_EDIT_INTERVAL = 3.0
TAIL_LINES = 8


class ProgressReporter:
    """Копит строки прогресса и редактирует одно сообщение, а не спамит новыми.

    Правки чаще раза в несколько секунд Telegram отклоняет, поэтому между
    ними выдерживается интервал, а последнее состояние дописывается в конце.
    """

    def __init__(self, message: Message, header: str = "<b>Обход</b>") -> None:
        self._message = message
        self._header = header
        self._lines: deque[str] = deque(maxlen=TAIL_LINES)
        self._last_edit = 0.0
        self._pending = False
        self._lock = asyncio.Lock()

    async def __call__(self, text: str) -> None:
        self._lines.append(text)
        self._pending = True
        if time.monotonic() - self._last_edit >= MIN_EDIT_INTERVAL:
            await self.flush()

    async def flush(self) -> None:
        async with self._lock:
            if not self._pending:
                return
            body = "\n".join(self._lines)
            self._pending = False
            self._last_edit = time.monotonic()
            try:
                await self._message.edit_text(f"{self._header}\n\n{body}")
            except TelegramRetryAfter as exc:
                self._last_edit = time.monotonic() + exc.retry_after
            except TelegramBadRequest:
                # «message is not modified» и подобное — не повод падать.
                pass

    async def finish(self, text: str) -> None:
        self._pending = True
        self._lines.clear()
        self._lines.append(text)
        with contextlib.suppress(TelegramBadRequest, TelegramRetryAfter):
            await self._message.edit_text(text)
