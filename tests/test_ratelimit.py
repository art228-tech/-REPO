from __future__ import annotations

import random

import pytest
from telethon.errors import FloodWaitError, PeerFloodError

from tgparser.ratelimit.guard import AccountFlagged, FloodGuard, ScanAborted, build_buckets
from tgparser.ratelimit.limiter import TokenBucket


def make_flood_wait(seconds: int) -> FloodWaitError:
    error = FloodWaitError.__new__(FloodWaitError)
    error.seconds = seconds
    error.message = f"FLOOD_WAIT_{seconds}"
    return error


def make_peer_flood() -> PeerFloodError:
    error = PeerFloodError.__new__(PeerFloodError)
    error.message = "PEER_FLOOD"
    return error


class TestTokenBucket:
    def test_rejects_non_positive_rate(self):
        with pytest.raises(ValueError, match="положительным"):
            TokenBucket(0)

    def test_starts_full(self, clock):
        bucket = TokenBucket(100, clock=clock)
        assert bucket.tokens == pytest.approx(10.0)

    def test_consumes_until_empty(self, clock):
        bucket = TokenBucket(100, capacity=3, clock=clock)
        assert bucket.try_consume()
        assert bucket.try_consume()
        assert bucket.try_consume()
        assert not bucket.try_consume()

    def test_refills_over_time(self, clock):
        bucket = TokenBucket(3600, capacity=2, clock=clock)  # 1 токен в секунду
        bucket.try_consume()
        bucket.try_consume()
        assert not bucket.try_consume()
        clock.advance(1.0)
        assert bucket.try_consume()

    def test_capacity_caps_refill(self, clock):
        bucket = TokenBucket(3600, capacity=2, clock=clock)
        clock.advance(1000)
        assert bucket.tokens <= 2.0 or bucket.time_until_available(2) == 0

    def test_time_until_available(self, clock):
        bucket = TokenBucket(3600, capacity=1, clock=clock)
        bucket.try_consume()
        assert bucket.time_until_available() == pytest.approx(1.0, abs=0.01)

    async def test_consume_waits(self, clock, fake_sleeper, sleep_log):
        bucket = TokenBucket(3600, capacity=1, clock=clock)
        await bucket.consume(sleeper=fake_sleeper)
        waited = await bucket.consume(sleeper=fake_sleeper)
        assert waited == pytest.approx(1.0, abs=0.01)
        assert sleep_log


class TestFloodGuard:
    async def test_passes_result_through(self, guard):
        async def call():
            return "готово"

        assert await guard.call("history", call) == "готово"
        assert guard.stats.calls["history"] == 1

    async def test_short_flood_wait_is_retried(self, guard, sleep_log):
        attempts = []

        async def call():
            attempts.append(1)
            if len(attempts) == 1:
                raise make_flood_wait(10)
            return "ок"

        assert await guard.call("history", call) == "ок"
        assert len(attempts) == 2
        assert 11 in sleep_log
        assert guard.stats.flood_events == 1

    async def test_long_flood_wait_aborts_run(self, guard):
        async def call():
            raise make_flood_wait(9999)

        with pytest.raises(ScanAborted, match="9999"):
            await guard.call("history", call)

    async def test_peer_flood_flags_account(self, guard):
        async def call():
            raise make_peer_flood()

        with pytest.raises(AccountFlagged):
            await guard.call("roster", call)
        assert guard.flagged

    async def test_flag_blocks_all_later_calls(self, guard):
        async def boom():
            raise make_peer_flood()

        async def fine():
            return "ок"

        with pytest.raises(AccountFlagged):
            await guard.call("roster", boom)
        # Пометка не снимается сама: пересидеть PeerFlood паузами нельзя.
        with pytest.raises(AccountFlagged):
            await guard.call("history", fine)

    async def test_budget_throttles_roster_harder_than_history(self, clock, fake_sleeper):
        guard = FloodGuard(
            buckets=build_buckets(20, 240, clock=clock),
            min_delay=0.0,
            max_delay=0.0,
            sleeper=fake_sleeper,
            rng=random.Random(0),
        )
        roster = guard._buckets["roster"]
        history = guard._buckets["history"]
        assert roster.rate_per_hour < history.rate_per_hour
        assert roster.capacity < history.capacity

    async def test_jitter_is_applied(self, clock, fake_sleeper, sleep_log):
        guard = FloodGuard(
            buckets=build_buckets(1000, 1000, clock=clock),
            min_delay=1.0,
            max_delay=2.0,
            sleeper=fake_sleeper,
            rng=random.Random(1),
        )

        async def call():
            return None

        await guard.call("history", call)
        assert sleep_log
        assert 1.0 <= sleep_log[-1] <= 2.0

    def test_rejects_bad_delay_range(self):
        with pytest.raises(ValueError, match="задержки"):
            FloodGuard(buckets={}, min_delay=5.0, max_delay=1.0)
