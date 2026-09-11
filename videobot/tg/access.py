"""Кто может пользоваться ботом и как часто.

Три заслона подряд, от самого дешёвого к самому дорогому:

1. Незнакомый человек отсекается до всякой работы с базой — на него не тратится
   ни запрос, ни ответ. Отвечать «нет доступа» на каждое нажатие нельзя: тогда
   спамом можно раскачать самого бота, отвечающего на спам.
2. Свой, но частящий, придерживается счётчиком: столько-то действий в минуту.
   Предупреждение шлётся один раз за окно, дальше молчание.
3. Если сторож нагрузки поставил бота на паузу, человек получает понятное
   «занят, подождите» вместо тишины.
"""
from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from ..db import Base
from ..logs import get_logger

log = get_logger("доступ")

WINDOW_S = 60.0


class Access(BaseMiddleware):
    def __init__(self, base: Base, settings, guard):
        self.base = base
        self.settings = settings
        self.guard = guard
        self._hits: dict[int, deque[float]] = defaultdict(deque)
        self._warned: dict[int, float] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user is None or user.is_bot:
            return None

        person = self._settle(user)
        if person is None or not person["has_access"]:
            return None

        if not self._allowed(user.id):
            await self._say(event, "Слишком часто. Подождите минуту.")
            return None

        if self.guard.paused:
            await self._say(
                event,
                "Компьютер сейчас занят другой работой — попробуйте через минуту.")
            return None

        data["person"] = person
        data["base"] = self.base
        data["settings"] = self.settings
        return await handler(event, data)

    def _settle(self, user):
        """Находит человека в базе, попутно назначая первого админа."""
        name = user.full_name or (user.username or str(user.id))
        self.base.remember_person(user.id, name)

        person = self.base.person(user.id)
        if person is not None and person["is_admin"]:
            return person

        if not self.base.admin_ids():
            # Админа ещё нет. Им становится либо тот, чей ID записан в
            # настройках, либо первый, кто нажал «Старт», — и дальше эта дверь
            # закрывается навсегда.
            wanted = int(self.settings.admin_id or 0)
            if wanted in (0, user.id):
                self.base.make_admin(user.id)
                log.info("Админом стал %s (%d)", name, user.id)
                return self.base.person(user.id)

        return person

    def _allowed(self, tg_id: int) -> bool:
        now = time.monotonic()
        hits = self._hits[tg_id]
        while hits and now - hits[0] > WINDOW_S:
            hits.popleft()

        if len(hits) >= self.settings.actions_per_minute:
            return False

        hits.append(now)
        return True

    def _should_warn(self, tg_id: int) -> bool:
        now = time.monotonic()
        if now - self._warned.get(tg_id, 0.0) < WINDOW_S:
            return False
        self._warned[tg_id] = now
        return True

    async def _say(self, event: TelegramObject, text: str) -> None:
        user = getattr(event, "from_user", None)
        if user is not None and not self._should_warn(user.id):
            return
        try:
            if isinstance(event, CallbackQuery):
                await event.answer(text, show_alert=False)
            elif isinstance(event, Message):
                await event.answer(text)
        except Exception:  # noqa: BLE001 - предупреждение не стоит падения
            pass
