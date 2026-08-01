from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from tgparser.db.models import SourceKind
from tgparser.db.repo import AccountRepo, ChatStateRepo, CollectedUser, LeadRepo


def user(uid: int, username: str | None = None, chat_id: int = -1001) -> CollectedUser:
    return CollectedUser(
        tg_user_id=uid,
        username=username,
        first_name="Имя",
        chat_id=chat_id,
        chat_title="Чат",
        message_id=uid * 10,
        message_link=f"https://t.me/c/1/{uid * 10}",
        source=SourceKind.HISTORY,
    )


class TestLeadDedup:
    async def test_adds_new_lead(self, db):
        async with db.session() as session:
            lead = await LeadRepo(session).add(user(1, "ivanov"))
        assert lead is not None
        assert lead.username == "ivanov"

    async def test_second_add_returns_none(self, db):
        async with db.session() as session:
            repo = LeadRepo(session)
            assert await repo.add(user(1, "ivanov")) is not None
            assert await repo.add(user(1, "ivanov")) is None

    async def test_same_person_in_other_chat_is_not_duplicated(self, db):
        async with db.session() as session:
            repo = LeadRepo(session)
            await repo.add(user(1, "ivanov", chat_id=-1001))
            assert await repo.add(user(1, "ivanov", chat_id=-1002)) is None
            assert await repo.count() == 1

    async def test_keeps_first_chat_context(self, db):
        async with db.session() as session:
            repo = LeadRepo(session)
            first = await repo.add(user(1, "ivanov", chat_id=-1001))
            await repo.add(user(1, "ivanov", chat_id=-1002))
            assert first.chat_id == -1001

    async def test_all_user_ids_returns_known(self, db):
        async with db.session() as session:
            repo = LeadRepo(session)
            await repo.add(user(1))
            await repo.add(user(2))
            assert await repo.all_user_ids() == {1, 2}

    async def test_manual_entries_excluded_from_user_ids(self, db):
        async with db.session() as session:
            repo = LeadRepo(session)
            await repo.add_manual("ivanov")
            assert await repo.all_user_ids() == set()


class TestManualAdd:
    async def test_creates_entry(self, db):
        async with db.session() as session:
            lead, created = await LeadRepo(session).add_manual("@ivanov")
        assert created
        assert lead.username == "ivanov"
        assert lead.source == SourceKind.MANUAL.value

    async def test_duplicate_returns_existing(self, db):
        async with db.session() as session:
            repo = LeadRepo(session)
            await repo.add_manual("ivanov")
            lead, created = await repo.add_manual("IVANOV")
        assert not created
        assert lead.username == "ivanov"

    async def test_note_is_saved(self, db):
        async with db.session() as session:
            lead, _ = await LeadRepo(session).add_manual("ivanov", note="с конференции")
        assert lead.note == "с конференции"


class TestStats:
    async def test_counts_by_category(self, db):
        async with db.session() as session:
            repo = LeadRepo(session)
            await repo.add(user(1, "tagged"))
            untagged = await repo.add(user(2, None, chat_id=-1002))
            await repo.set_archive(untagged, "https://t.me/c/5/1", anonymized=True)
            await repo.add_manual("manual_one")
            stats = await repo.stats()

        assert stats["leads"] == 3
        assert stats["with_username"] == 2
        assert stats["without_username"] == 1
        assert stats["archived_cards"] == 1
        assert stats["anonymized_cards"] == 1
        assert stats["manual"] == 1
        assert stats["chats"] == 2


class TestChatState:
    async def test_get_or_create_is_idempotent(self, db):
        async with db.session() as session:
            repo = ChatStateRepo(session)
            first = await repo.get_or_create(1, -1001, "Чат", "supergroup")
            second = await repo.get_or_create(1, -1001, "Чат", "supergroup")
        assert first.id == second.id

    async def test_reset_clears_progress(self, db):
        async with db.session() as session:
            repo = ChatStateRepo(session)
            state = await repo.get_or_create(1, -1001, "Чат", "supergroup")
            state.oldest_message_id = 500
            state.history_done = True
            state.roster_offset = 400
            await session.flush()

        async with db.session() as session:
            count = await ChatStateRepo(session).reset(1)
            states = await ChatStateRepo(session).for_account(1)

        assert count == 1
        assert states[0].oldest_message_id is None
        assert states[0].history_done is False
        assert states[0].roster_offset == 0


class TestAccountBlocking:
    async def test_new_account_is_not_blocked(self, db):
        async with db.session() as session:
            account = await AccountRepo(session).upsert_session(
                "+79990000000", b"enc", 1, "ivanov"
            )
        assert not AccountRepo.is_blocked(account)

    async def test_block_sets_deadline(self, db):
        async with db.session() as session:
            repo = AccountRepo(session)
            account = await repo.upsert_session("+79990000000", b"enc", 1, "ivanov")
            await repo.block(account, 24, "PeerFlood")
        assert AccountRepo.is_blocked(account)
        assert account.block_reason == "PeerFlood"

    async def test_block_expires(self, db):
        async with db.session() as session:
            repo = AccountRepo(session)
            account = await repo.upsert_session("+79990000000", b"enc", 1, "ivanov")
            await repo.block(account, 1, "PeerFlood")
        later = datetime.now(UTC) + timedelta(hours=2)
        assert not AccountRepo.is_blocked(account, now=later)

    async def test_naive_datetime_from_sqlite_is_handled(self, db):
        """SQLite отдаёт время без таймзоны — сравнение не должно падать."""
        async with db.session() as session:
            repo = AccountRepo(session)
            account = await repo.upsert_session("+79990000000", b"enc", 1, "ivanov")
            await repo.block(account, 24, "PeerFlood")
            account_id = account.id

        async with db.session() as session:
            reloaded = await AccountRepo(session).get(account_id)
            assert AccountRepo.is_blocked(reloaded)

    async def test_upsert_reactivates_and_unblocks(self, db):
        async with db.session() as session:
            repo = AccountRepo(session)
            account = await repo.upsert_session("+79990000000", b"enc", 1, "ivanov")
            await repo.block(account, 24, "PeerFlood")
            again = await repo.upsert_session("+79990000000", b"enc2", 1, "ivanov")
        assert not AccountRepo.is_blocked(again)
        assert again.session_enc == b"enc2"

    async def test_first_active_returns_none_when_empty(self, db):
        async with db.session() as session:
            assert await AccountRepo(session).first_active() is None


@pytest.mark.parametrize("phone", ["+79990000001", "+79990000002"])
async def test_lookup_by_phone(db, phone):
    async with db.session() as session:
        repo = AccountRepo(session)
        await repo.upsert_session(phone, b"enc", 1, None)
        assert await repo.get_by_phone(phone) is not None
