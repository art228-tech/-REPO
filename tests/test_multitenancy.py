"""Изоляция данных между пользователями бота.

Доступ открытый, поэтому в одной базе живут данные разных людей. Каждая
проверка здесь отвечает на вопрос «может ли один пользователь увидеть или
задеть чужое».
"""

from __future__ import annotations

import pytest

from tests.factories import make_channel, make_message, make_user
from tests.fakes import ChatFixture, FakeTelegramClient
from tgparser.core.archive import Archive
from tgparser.core.scanner import Scanner
from tgparser.db.repo import AccountRepo, ChatStateRepo, CollectedUser, LeadRepo
from tgparser.db.settings_store import ScanSettings, load_settings, save_settings
from tgparser.export.service import ExportFilter, export, fetch_leads
from tgparser.ratelimit.guard import FloodGuard, build_buckets

ALICE = 1001
BOB = 2002


def lead_of(uid: int, username: str) -> CollectedUser:
    return CollectedUser(tg_user_id=uid, username=username, chat_id=-100, chat_title="Чат")


class TestLeadIsolation:
    async def test_each_owner_sees_only_own_leads(self, db):
        async with db.session() as session:
            await LeadRepo(session, ALICE).add(lead_of(1, "alice_lead"))
            await LeadRepo(session, BOB).add(lead_of(2, "bob_lead"))

        async with db.session() as session:
            assert await LeadRepo(session, ALICE).count() == 1
            assert await LeadRepo(session, BOB).count() == 1
            alice = await fetch_leads(session, ALICE)
            bob = await fetch_leads(session, BOB)

        assert [item.username for item in alice] == ["alice_lead"]
        assert [item.username for item in bob] == ["bob_lead"]

    async def test_same_person_can_be_in_both_bases(self, db):
        """Один и тот же человек — валидный лид для двух разных пользователей."""
        async with db.session() as session:
            assert await LeadRepo(session, ALICE).add(lead_of(42, "shared")) is not None
            assert await LeadRepo(session, BOB).add(lead_of(42, "shared")) is not None

        async with db.session() as session:
            assert await LeadRepo(session, ALICE).count() == 1
            assert await LeadRepo(session, BOB).count() == 1

    async def test_dedup_still_works_inside_one_owner(self, db):
        async with db.session() as session:
            repo = LeadRepo(session, ALICE)
            assert await repo.add(lead_of(42, "shared")) is not None
            assert await repo.add(lead_of(42, "shared")) is None

    async def test_seen_set_does_not_leak(self, db):
        async with db.session() as session:
            await LeadRepo(session, ALICE).add(lead_of(1, "alice_lead"))

        async with db.session() as session:
            assert await LeadRepo(session, ALICE).all_user_ids() == {1}
            assert await LeadRepo(session, BOB).all_user_ids() == set()

    async def test_manual_tags_are_separate(self, db):
        async with db.session() as session:
            await LeadRepo(session, ALICE).add_manual("ivanov")
            _, created = await LeadRepo(session, BOB).add_manual("ivanov")
        assert created is True

    async def test_stats_are_per_owner(self, db):
        async with db.session() as session:
            await LeadRepo(session, ALICE).add(lead_of(1, "one_tag"))
            await LeadRepo(session, ALICE).add(lead_of(2, "two_tag"))
            await LeadRepo(session, BOB).add(lead_of(3, "three_tag"))

        async with db.session() as session:
            assert (await LeadRepo(session, ALICE).stats())["leads"] == 2
            assert (await LeadRepo(session, BOB).stats())["leads"] == 1


class TestAccountIsolation:
    async def test_owner_sees_only_own_account(self, db):
        async with db.session() as session:
            await AccountRepo(session, ALICE).upsert_session(
                "+79990000001", b"alice", 1, "alice"
            )

        async with db.session() as session:
            assert await AccountRepo(session, ALICE).first_active() is not None
            assert await AccountRepo(session, BOB).first_active() is None

    async def test_account_not_readable_by_id_from_another_owner(self, db):
        async with db.session() as session:
            account = await AccountRepo(session, ALICE).upsert_session(
                "+79990000001", b"alice", 1, "alice"
            )
            account_id = account.id

        async with db.session() as session:
            assert await AccountRepo(session, ALICE).get(account_id) is not None
            # Прямой перебор id не должен отдавать чужую сессию.
            assert await AccountRepo(session, BOB).get(account_id) is None

    async def test_same_phone_for_two_owners(self, db):
        async with db.session() as session:
            await AccountRepo(session, ALICE).upsert_session("+79990000001", b"a", 1, None)
            await AccountRepo(session, BOB).upsert_session("+79990000001", b"b", 2, None)

        async with db.session() as session:
            alice = await AccountRepo(session, ALICE).first_active()
            bob = await AccountRepo(session, BOB).first_active()
        assert alice.id != bob.id
        assert alice.session_enc == b"a"
        assert bob.session_enc == b"b"

    async def test_block_affects_only_one_owner(self, db):
        async with db.session() as session:
            alice_repo = AccountRepo(session, ALICE)
            alice_account = await alice_repo.upsert_session("+79990000001", b"a", 1, None)
            await AccountRepo(session, BOB).upsert_session("+79990000002", b"b", 2, None)
            await alice_repo.block(alice_account, 24, "PeerFlood")

        async with db.session() as session:
            assert AccountRepo.is_blocked(await AccountRepo(session, ALICE).first_active())
            assert not AccountRepo.is_blocked(await AccountRepo(session, BOB).first_active())


class TestSettingsIsolation:
    async def test_settings_do_not_leak(self, db):
        async with db.session() as session:
            await save_settings(session, ALICE, ScanSettings(history_depth_days=7))

        async with db.session() as session:
            assert (await load_settings(session, ALICE)).history_depth_days == 7
            assert (await load_settings(session, BOB)).history_depth_days == 30

    async def test_roster_flag_is_per_owner(self, db):
        async with db.session() as session:
            await save_settings(session, ALICE, ScanSettings(collect_roster=True))

        async with db.session() as session:
            assert (await load_settings(session, ALICE)).collect_roster is True
            assert (await load_settings(session, BOB)).collect_roster is False


class TestExportIsolation:
    async def test_export_contains_only_own_rows(self, db, tmp_path):
        import json

        async with db.session() as session:
            await LeadRepo(session, ALICE).add(lead_of(1, "alice_lead"))
            await LeadRepo(session, BOB).add(lead_of(2, "bob_lead"))

        async with db.session() as session:
            result = await export(session, ALICE, "json", tmp_path, ScanSettings())

        payload = json.loads(result.path.read_text(encoding="utf-8"))
        assert [item["tag"] for item in payload] == ["@alice_lead"]

    async def test_filenames_do_not_collide(self, db, tmp_path):
        from datetime import UTC, datetime

        from tgparser.export.service import build_filename

        now = datetime(2026, 8, 1, tzinfo=UTC)
        assert build_filename("csv", ALICE, now) != build_filename("csv", BOB, now)

    async def test_filter_stays_within_owner(self, db, tmp_path):
        async with db.session() as session:
            await LeadRepo(session, ALICE).add(lead_of(1, "alice_lead"))
            await LeadRepo(session, BOB).add(lead_of(2, "bob_lead"))

        async with db.session() as session:
            found = await fetch_leads(session, BOB, ExportFilter(only_with_username=True))
        assert [item.username for item in found] == ["bob_lead"]


class TestScannerIsolation:
    async def _scan(self, db, owner_id: int, chat_id: int, user_id: int, tag: str):
        users = {user_id: make_user(user_id, tag)}
        chat = ChatFixture(
            entity=make_channel(chat_id), messages=[make_message(9, user_id)]
        )
        client = FakeTelegramClient([chat], users)
        guard = FloodGuard(
            buckets=build_buckets(10_000, 10_000),
            min_delay=0.0,
            max_delay=0.0,
            sleeper=_noop,
        )
        scanner = Scanner(
            client=client,
            guard=guard,
            settings=ScanSettings(min_delay_sec=0.0, max_delay_sec=0.0),
            db=db,
            account_id=owner_id,
            owner_id=owner_id,
            self_id=777,
            archive=Archive(client, guard),
        )
        return await scanner.run()

    async def test_scans_write_into_separate_bases(self, db):
        await self._scan(db, ALICE, 1001, 11, "alice_found")
        await self._scan(db, BOB, 1002, 22, "bob_found")

        async with db.session() as session:
            alice = await fetch_leads(session, ALICE)
            bob = await fetch_leads(session, BOB)

        assert [item.username for item in alice] == ["alice_found"]
        assert [item.username for item in bob] == ["bob_found"]

    async def test_same_user_found_by_both_is_kept_twice(self, db):
        await self._scan(db, ALICE, 1001, 42, "popular")
        report = await self._scan(db, BOB, 1002, 42, "popular")

        # Для Боба это новая запись, хотя у Алисы человек уже есть.
        assert report.new_leads == 1
        async with db.session() as session:
            assert await LeadRepo(session, BOB).count() == 1

    async def test_checkpoints_do_not_collide(self, db):
        await self._scan(db, ALICE, 1001, 11, "alice_found")
        await self._scan(db, BOB, 1002, 22, "bob_found")

        async with db.session() as session:
            alice_states = await ChatStateRepo(session).for_account(ALICE)
            bob_states = await ChatStateRepo(session).for_account(BOB)

        assert len(alice_states) == 1
        assert len(bob_states) == 1
        assert alice_states[0].chat_id != bob_states[0].chat_id


async def _noop(_seconds: float) -> None:
    return None


@pytest.mark.parametrize("owner_id", [ALICE, BOB])
async def test_fresh_owner_starts_empty(db, owner_id):
    async with db.session() as session:
        assert await LeadRepo(session, owner_id).count() == 0
        assert await AccountRepo(session, owner_id).first_active() is None
