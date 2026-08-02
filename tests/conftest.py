from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from tgparser.db.engine import Database
from tgparser.db.settings_store import ScanSettings
from tgparser.ratelimit.guard import FloodGuard, build_buckets


class FakeClock:
    """Управляемое время для тестов токен-бакета."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def sleep_log() -> list[float]:
    return []


@pytest.fixture
def fake_sleeper(sleep_log: list[float], clock: FakeClock):
    """Мгновенный sleep, который двигает поддельные часы и пишет лог."""

    async def _sleep(seconds: float) -> None:
        sleep_log.append(seconds)
        clock.advance(seconds)

    return _sleep


@pytest.fixture
def guard(fake_sleeper, clock: FakeClock) -> FloodGuard:
    import random

    return FloodGuard(
        buckets=build_buckets(1000, 5000, clock=clock),
        min_delay=0.0,
        max_delay=0.0,
        max_flood_wait=300,
        sleeper=fake_sleeper,
        rng=random.Random(0),
    )


@pytest.fixture
async def db(tmp_path) -> AsyncIterator[Database]:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'test.sqlite3'}")
    await database.create_all()
    try:
        yield database
    finally:
        await database.dispose()


@pytest.fixture
def scan_settings() -> ScanSettings:
    return ScanSettings(
        history_depth_days=30,
        collect_history=True,
        collect_comments=True,
        collect_roster=False,
        forward_untagged=True,
        min_delay_sec=0.0,
        max_delay_sec=0.0,
    )
