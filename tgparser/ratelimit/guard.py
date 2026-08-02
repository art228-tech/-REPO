"""Обёртка над вызовами MTProto: бюджеты, джиттер, FloodWait, PeerFlood.

Разделение важное:

* ``FloodWaitError`` — обычный рейт-лимит, у него есть число секунд. Короткий
  пересиживаем, длинный означает, что темп выбран неверно, — прерываем прогон
  и возобновляемся позже с чекпоинта.
* ``PeerFloodError`` — не рейт-лимит, а поведенческая пометка аккаунта. Числа
  секунд у неё нет, пересидеть паузами нельзя. Единственная разумная реакция —
  немедленно остановить всё и вывести аккаунт из работы на сутки.
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

from telethon.errors import FloodWaitError, PeerFloodError

logger = logging.getLogger(__name__)

T = TypeVar("T")


class ScanAborted(RuntimeError):
    """Прогон остановлен, состояние сохранено, возобновление возможно."""


class AccountFlagged(ScanAborted):
    """Аккаунт получил PeerFlood. Требуется длительная пауза."""


@dataclass(slots=True)
class GuardStats:
    calls: dict[str, int] = field(default_factory=dict)
    budget_waits: float = 0.0
    flood_waits: float = 0.0
    flood_events: int = 0

    def record(self, bucket: str) -> None:
        self.calls[bucket] = self.calls.get(bucket, 0) + 1

    @property
    def total_calls(self) -> int:
        return sum(self.calls.values())


class FloodGuard:
    """Единая точка, через которую проходят все обращения к Telegram."""

    def __init__(
        self,
        buckets: dict[str, Any],
        min_delay: float = 1.5,
        max_delay: float = 4.0,
        max_flood_wait: int = 300,
        sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
        rng: random.Random | None = None,
    ) -> None:
        if min_delay < 0 or max_delay < min_delay:
            raise ValueError("Некорректный диапазон задержки")
        self._buckets = buckets
        self._min_delay = min_delay
        self._max_delay = max_delay
        self._max_flood_wait = max_flood_wait
        self._sleep = sleeper
        self._rng = rng or random.Random()
        self.stats = GuardStats()
        self._flagged = False

    @property
    def flagged(self) -> bool:
        return self._flagged

    def retune(self, buckets: dict[str, Any]) -> None:
        """Заменить бюджеты на ходу.

        Разгон снимается по числу успешных запросов, а один прогон идёт
        часами: без пересчёта посреди работы он весь шёл бы на сниженном
        темпе, даже когда условие снятия давно выполнено.
        """
        self._buckets = buckets

    async def _pace(self, bucket: str) -> None:
        limiter = self._buckets.get(bucket)
        if limiter is not None:
            self.stats.budget_waits += await limiter.consume(sleeper=self._sleep)
        # Джиттер: ровные интервалы между запросами сами по себе выглядят ботом.
        await self._sleep(self._rng.uniform(self._min_delay, self._max_delay))

    async def call(
        self,
        bucket: str,
        func: Callable[..., Awaitable[T]],
        *args: Any,
        **kwargs: Any,
    ) -> T:
        """Выполнить запрос с соблюдением бюджета и обработкой флуд-ошибок."""
        if self._flagged:
            raise AccountFlagged("Аккаунт помечен PeerFlood, работа остановлена")

        await self._pace(bucket)
        self.stats.record(bucket)
        try:
            return await func(*args, **kwargs)
        except PeerFloodError as exc:
            self._flagged = True
            logger.error("PeerFlood на вызове %s: %s", bucket, exc)
            raise AccountFlagged(
                "Telegram пометил аккаунт как спам-риск (PeerFlood). "
                "Прогон остановлен, аккаунт выведен из работы."
            ) from exc
        except FloodWaitError as exc:
            self.stats.flood_events += 1
            if exc.seconds > self._max_flood_wait:
                logger.warning(
                    "FloodWait %sс превышает порог %sс — прерываю прогон",
                    exc.seconds,
                    self._max_flood_wait,
                )
                raise ScanAborted(
                    f"Telegram требует паузу {exc.seconds} с — это больше порога "
                    f"{self._max_flood_wait} с. Прогон остановлен, прогресс сохранён."
                ) from exc
            logger.info("FloodWait %sс на %s — пережидаю", exc.seconds, bucket)
            self.stats.flood_waits += exc.seconds
            await self._sleep(exc.seconds + 1)
            return await func(*args, **kwargs)

    async def iterate(
        self,
        bucket: str,
        agen_factory: Callable[[], Any],
    ) -> Any:
        """Асинхронный итератор с оплатой бюджета за каждую выданную порцию."""
        agen = agen_factory()
        while True:
            if self._flagged:
                raise AccountFlagged("Аккаунт помечен PeerFlood, работа остановлена")
            try:
                item = await self.call(bucket, agen.__anext__)
            except StopAsyncIteration:
                return
            yield item


def build_buckets(
    roster_per_hour: int,
    history_per_hour: int,
    write_per_hour: int = 120,
    clock: Callable[[], float] | None = None,
) -> dict[str, Any]:
    """Бюджеты по типам запросов.

    Перебор участников стоит дорого (это главный триггер), чтение истории —
    обычное поведение клиента, ему бюджет намного щедрее.
    """
    from tgparser.ratelimit.limiter import TokenBucket

    kwargs = {"clock": clock} if clock is not None else {}
    return {
        "roster": TokenBucket(roster_per_hour, **kwargs),
        "history": TokenBucket(history_per_hour, **kwargs),
        "meta": TokenBucket(max(60, history_per_hour), **kwargs),
        "write": TokenBucket(write_per_hour, **kwargs),
    }
