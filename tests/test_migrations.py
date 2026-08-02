"""Дописывание столбцов в существующую базу.

``create_all`` создаёт только отсутствующие таблицы и молча игнорирует новые
столбцы в существующих. На проде это дало «no such column» после добавления
поля в модель, поэтому поведение закреплено тестами.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select, text

from tgparser.db.engine import Database
from tgparser.db.models import Account, Lead
from tgparser.db.repo import AccountRepo, CollectedUser, LeadRepo

OWNER = 555


async def columns_of(db: Database, table: str) -> set[str]:
    async with db.session() as session:
        rows = await session.execute(text(f"PRAGMA table_info({table})"))
        return {row[1] for row in rows}


@pytest.fixture
async def legacy_db(tmp_path):
    """База, из которой удалены поздние столбцы — как на сервере до обновления."""
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'legacy.sqlite3'}")
    await database.create_all()

    # SQLite не умеет DROP COLUMN в старых версиях, поэтому таблицу
    # пересобираем без новых полей.
    async with database.session() as session:
        await session.execute(text("DROP TABLE accounts"))
        await session.execute(
            text(
                "CREATE TABLE accounts ("
                " id INTEGER NOT NULL PRIMARY KEY,"
                " owner_id BIGINT NOT NULL,"
                " phone VARCHAR(32) NOT NULL,"
                " tg_user_id BIGINT,"
                " username VARCHAR(64),"
                " session_enc BLOB NOT NULL,"
                " proxy VARCHAR(255),"
                " api_id INTEGER,"
                " api_hash_enc BLOB,"
                " archive_channel_id BIGINT,"
                " is_active BOOLEAN NOT NULL,"
                " created_at DATETIME NOT NULL,"
                " blocked_until DATETIME,"
                " block_reason VARCHAR(255))"
            )
        )
        await session.execute(
            text(
                "INSERT INTO accounts (id, owner_id, phone, session_enc, is_active,"
                " created_at) VALUES (1, :owner, '+79990000000', X'00', 1,"
                " '2026-08-01 00:00:00')"
            ),
            {"owner": OWNER},
        )
    try:
        yield database
    finally:
        await database.dispose()


class TestMigrate:
    async def test_missing_columns_are_added(self, legacy_db):
        before = await columns_of(legacy_db, "accounts")
        assert "calls_done" not in before

        added = await legacy_db.migrate()

        assert "accounts.calls_done" in added
        assert "accounts.flood_events" in added
        after = await columns_of(legacy_db, "accounts")
        assert {"calls_done", "flood_events"} <= after

    async def test_existing_rows_get_the_default(self, legacy_db):
        """Старые строки не должны получить NULL там, где ожидается число."""
        await legacy_db.migrate()
        async with legacy_db.session() as session:
            account = await session.scalar(select(Account))
        assert account.calls_done == 0
        assert account.flood_events == 0

    async def test_queries_work_after_migration(self, legacy_db):
        await legacy_db.migrate()
        async with legacy_db.session() as session:
            account = await AccountRepo(session, OWNER).first_active()
            assert account is not None
            account.calls_done += 7

        async with legacy_db.session() as session:
            account = await AccountRepo(session, OWNER).first_active()
        assert account.calls_done == 7

    async def test_migration_is_idempotent(self, legacy_db):
        first = await legacy_db.migrate()
        second = await legacy_db.migrate()
        assert first
        assert second == []

    async def test_nothing_to_do_on_fresh_db(self, db):
        assert await db.migrate() == []

    async def test_data_survives_migration(self, legacy_db):
        async with legacy_db.session() as session:
            await LeadRepo(session, OWNER).add(
                CollectedUser(tg_user_id=1, username="ivanov")
            )

        await legacy_db.migrate()

        async with legacy_db.session() as session:
            leads = list(await session.scalars(select(Lead)))
            account = await session.scalar(select(Account))
        assert [lead.username for lead in leads] == ["ivanov"]
        assert account.phone == "+79990000000"
