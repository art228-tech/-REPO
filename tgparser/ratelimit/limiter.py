"""Токен-бакет с почасовым бюджетом вызовов."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable


class TokenBucket:
    """Ограничитель «не больше N вызовов в час».

    Бакет пополняется непрерывно, а не раз в час, поэтому вызовы размазываются
    по времени вместо всплеска в начале каждого часа. Именно всплески и читаются
    антиспамом как автоматизация.
    """

    def __init__(
        self,
        rate_per_hour: int,
        capacity: float | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if rate_per_hour <= 0:
            raise ValueError("rate_per_hour должен быть положительным")
        self.rate_per_hour = rate_per_hour
        self._rate_per_sec = rate_per_hour / 3600.0
        # Небольшая ёмкость позволяет короткий разгон, но не «всё за раз».
        self.capacity = float(
            capacity if capacity is not None else max(1, rate_per_hour // 10)
        )
        self._tokens = self.capacity
        self._clock = clock
        self._last = clock()
        self._lock = asyncio.Lock()

    @property
    def tokens(self) -> float:
        return self._tokens

    def _refill(self) -> None:
        now = self._clock()
        elapsed = max(0.0, now - self._last)
        self._last = now
        self._tokens = min(self.capacity, self._tokens + elapsed * self._rate_per_sec)

    def time_until_available(self, amount: float = 1.0) -> float:
        """Сколько секунд ждать до появления `amount` токенов."""
        self._refill()
        if self._tokens >= amount:
            return 0.0
        return (amount - self._tokens) / self._rate_per_sec

    def try_consume(self, amount: float = 1.0) -> bool:
        self._refill()
        if self._tokens >= amount:
            self._tokens -= amount
            return True
        return False

    async def consume(self, amount: float = 1.0, sleeper=asyncio.sleep) -> float:
        """Дождаться токена. Возвращает суммарное время ожидания."""
        waited = 0.0
        async with self._lock:
            while True:
                delay = self.time_until_available(amount)
                if delay <= 0:
                    self._tokens -= amount
                    return waited
                waited += delay
                await sleeper(delay)
