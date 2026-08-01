from __future__ import annotations

import pytest
from telethon.errors import ChatForwardsRestrictedError, PeerFloodError
from telethon.utils import get_peer_id

from tests.factories import (
    make_basic_group,
    make_channel,
    make_message,
    make_service_message,
    make_user,
)
from tests.fakes import ChatFixture, FakeTelegramClient
from tgparser.core.archive import Archive
from tgparser.core.scanner import Scanner
from tgparser.db.models import ChatState, SourceKind

SELF_ID = 777
OWNER_A = 1001
OWNER_B = 2002


async def run_scanner(client, db, settings, account_id: int = 1, owner_id: int = OWNER_A):
    from tgparser.ratelimit.guard import FloodGuard, build_buckets

    guard = FloodGuard(
        buckets=build_buckets(10_000, 10_000),
        min_delay=0.0,
        max_delay=0.0,
        sleeper=_noop_sleep,
    )
    scanner = Scanner(
        client=client,
        guard=guard,
        settings=settings,
        db=db,
        account_id=account_id,
        owner_id=owner_id,
        self_id=SELF_ID,
        archive=Archive(client, guard),
    )
    return await scanner.run()


async def _noop_sleep(_seconds: float) -> None:
    return None


async def leads_in(db) -> list:
    async with db.session() as session:
        from sqlalchemy import select

        from tgparser.db.models import Lead

        rows = await session.scalars(select(Lead).order_by(Lead.tg_user_id))
        return list(rows)


class TestHistoryCollection:
    async def test_collects_message_authors(self, db, scan_settings):
        users = {1: make_user(1, "alpha_tag"), 2: make_user(2, "beta_tag")}
        chat = ChatFixture(
            entity=make_channel(1001, "Станки", username="stanki"),
            messages=[make_message(30, 1), make_message(29, 2)],
        )
        client = FakeTelegramClient([chat], users)

        report = await run_scanner(client, db, scan_settings)

        assert report.new_leads == 2
        assert {lead.username for lead in await leads_in(db)} == {"alpha_tag", "beta_tag"}

    async def test_no_profile_requests_are_made(self, db, scan_settings):
        """Профили приезжают вместе с историей — отдельных запросов быть не должно."""
        users = {i: make_user(i, f"user_{i}") for i in range(1, 21)}
        chat = ChatFixture(
            entity=make_channel(1001),
            messages=[make_message(100 - i, i) for i in range(1, 21)],
        )
        client = FakeTelegramClient([chat], users)

        await run_scanner(client, db, scan_settings)

        assert client.count("GetParticipants") == 0
        assert len(await leads_in(db)) == 20

    async def test_repeated_author_stored_once(self, db, scan_settings):
        users = {1: make_user(1, "alpha_tag")}
        chat = ChatFixture(
            entity=make_channel(1001),
            messages=[make_message(30, 1), make_message(29, 1), make_message(28, 1)],
        )
        client = FakeTelegramClient([chat], users)

        report = await run_scanner(client, db, scan_settings)

        assert report.new_leads == 1
        assert len(await leads_in(db)) == 1

    async def test_same_person_across_two_chats_stored_once(self, db, scan_settings):
        users = {1: make_user(1, "alpha_tag")}
        first = ChatFixture(entity=make_channel(1001, "Первый"), messages=[make_message(9, 1)])
        second = ChatFixture(entity=make_channel(1002, "Второй"), messages=[make_message(9, 1)])
        client = FakeTelegramClient([first, second], users)

        await run_scanner(client, db, scan_settings)

        stored = await leads_in(db)
        assert len(stored) == 1
        assert stored[0].chat_title == "Первый"

    async def test_dedup_survives_second_run(self, db, scan_settings):
        users = {1: make_user(1, "alpha_tag")}
        chat = ChatFixture(entity=make_channel(1001), messages=[make_message(9, 1)])

        await run_scanner(FakeTelegramClient([chat], users), db, scan_settings)
        second = await run_scanner(FakeTelegramClient([chat], users), db, scan_settings)

        assert second.new_leads == 0
        assert len(await leads_in(db)) == 1

    async def test_cutoff_stops_at_depth(self, db, scan_settings):
        scan_settings.history_depth_days = 30
        users = {1: make_user(1, "fresh_tag"), 2: make_user(2, "stale_tag")}
        chat = ChatFixture(
            entity=make_channel(1001),
            messages=[make_message(30, 1, days_ago=5), make_message(29, 2, days_ago=90)],
        )
        client = FakeTelegramClient([chat], users)

        await run_scanner(client, db, scan_settings)

        assert {lead.username for lead in await leads_in(db)} == {"fresh_tag"}

    async def test_zero_depth_takes_everything(self, db, scan_settings):
        scan_settings.history_depth_days = 0
        users = {1: make_user(1, "fresh_tag"), 2: make_user(2, "ancient_tag")}
        chat = ChatFixture(
            entity=make_channel(1001),
            messages=[make_message(30, 1, days_ago=1), make_message(29, 2, days_ago=900)],
        )
        client = FakeTelegramClient([chat], users)

        await run_scanner(client, db, scan_settings)
        assert len(await leads_in(db)) == 2

    async def test_message_link_uses_public_username(self, db, scan_settings):
        users = {1: make_user(1, "alpha_tag")}
        chat = ChatFixture(
            entity=make_channel(1001, username="stanki"), messages=[make_message(42, 1)]
        )
        await run_scanner(FakeTelegramClient([chat], users), db, scan_settings)

        stored = await leads_in(db)
        assert stored[0].message_link == "https://t.me/stanki/42"

    async def test_snippet_is_saved(self, db, scan_settings):
        users = {1: make_user(1, "alpha_tag")}
        chat = ChatFixture(
            entity=make_channel(1001),
            messages=[make_message(42, 1, text="нужен подрядчик по фрезеровке")],
        )
        await run_scanner(FakeTelegramClient([chat], users), db, scan_settings)

        assert (await leads_in(db))[0].snippet == "нужен подрядчик по фрезеровке"


class TestSkipping:
    async def test_bots_and_deleted_are_skipped(self, db, scan_settings):
        users = {
            1: make_user(1, "human_tag"),
            2: make_user(2, "some_bot", bot=True),
            3: make_user(3, deleted=True),
        }
        chat = ChatFixture(
            entity=make_channel(1001),
            messages=[make_message(30, 1), make_message(29, 2), make_message(28, 3)],
        )
        await run_scanner(FakeTelegramClient([chat], users), db, scan_settings)

        assert {lead.username for lead in await leads_in(db)} == {"human_tag"}

    async def test_own_account_is_skipped(self, db, scan_settings):
        users = {SELF_ID: make_user(SELF_ID, "me_myself"), 1: make_user(1, "other_tag")}
        chat = ChatFixture(
            entity=make_channel(1001),
            messages=[make_message(30, SELF_ID), make_message(29, 1)],
        )
        await run_scanner(FakeTelegramClient([chat], users), db, scan_settings)

        assert {lead.username for lead in await leads_in(db)} == {"other_tag"}

    async def test_anonymous_admin_posts_are_skipped(self, db, scan_settings):
        users = {1: make_user(1, "human_tag")}
        chat = ChatFixture(
            entity=make_channel(1001),
            messages=[
                make_message(30, None, from_channel_id=1001),
                make_message(29, 1),
            ],
        )
        await run_scanner(FakeTelegramClient([chat], users), db, scan_settings)
        assert len(await leads_in(db)) == 1

    async def test_service_messages_are_skipped(self, db, scan_settings):
        users = {1: make_user(1, "human_tag"), 2: make_user(2, "joined_tag")}
        chat = ChatFixture(
            entity=make_channel(1001),
            messages=[make_message(30, 1), make_service_message(29, 2)],
        )
        await run_scanner(FakeTelegramClient([chat], users), db, scan_settings)

        assert {lead.username for lead in await leads_in(db)} == {"human_tag"}

    async def test_excluded_chat_is_not_visited(self, db, scan_settings):
        scan_settings.excluded_chats = ["@spamchat"]
        users = {1: make_user(1, "alpha_tag")}
        skipped = ChatFixture(
            entity=make_channel(1001, username="spamchat"), messages=[make_message(9, 1)]
        )
        client = FakeTelegramClient([skipped], users)

        report = await run_scanner(client, db, scan_settings)

        assert report.dialogs_total == 0
        assert client.count("GetHistory") == 0

    async def test_included_list_limits_to_whitelist(self, db, scan_settings):
        scan_settings.included_chats = ["@keepme"]
        users = {1: make_user(1, "alpha_tag"), 2: make_user(2, "beta_tag")}
        kept = ChatFixture(
            entity=make_channel(1001, username="keepme"), messages=[make_message(9, 1)]
        )
        other = ChatFixture(
            entity=make_channel(1002, username="other"), messages=[make_message(9, 2)]
        )
        await run_scanner(FakeTelegramClient([kept, other], users), db, scan_settings)

        assert {lead.username for lead in await leads_in(db)} == {"alpha_tag"}

    async def test_small_chats_can_be_skipped(self, db, scan_settings):
        scan_settings.min_participants = 50
        users = {1: make_user(1, "alpha_tag")}
        chat = ChatFixture(
            entity=make_channel(1001),
            messages=[make_message(9, 1)],
            participants_count=10,
        )
        report = await run_scanner(FakeTelegramClient([chat], users), db, scan_settings)

        assert report.chats[0].skipped is not None
        assert len(await leads_in(db)) == 0


class TestParticipantVisibility:
    async def test_hidden_participants_are_detected(self, db, scan_settings):
        scan_settings.collect_roster = True
        users = {1: make_user(1, "alpha_tag")}
        chat = ChatFixture(
            entity=make_channel(1001),
            messages=[make_message(9, 1)],
            participants=[make_user(50, "hidden_one")],
            participants_hidden=True,
        )
        client = FakeTelegramClient([chat], users)

        report = await run_scanner(client, db, scan_settings)

        assert report.chats[0].participants_visible is False
        # Ростер не запрашивается, когда список скрыт.
        assert client.count("GetParticipants") == 0
        assert {lead.username for lead in await leads_in(db)} == {"alpha_tag"}

    async def test_cannot_view_participants_is_respected(self, db, scan_settings):
        scan_settings.collect_roster = True
        chat = ChatFixture(
            entity=make_channel(1001),
            participants=[make_user(50, "hidden_one")],
            can_view_participants=False,
        )
        client = FakeTelegramClient([chat], {})

        report = await run_scanner(client, db, scan_settings)

        assert report.chats[0].participants_visible is False
        assert client.count("GetParticipants") == 0

    async def test_roster_collected_when_visible_and_enabled(self, db, scan_settings):
        scan_settings.collect_roster = True
        scan_settings.collect_history = False
        chat = ChatFixture(
            entity=make_channel(1001),
            participants=[make_user(50, "first_tag"), make_user(51, "second_tag")],
        )
        client = FakeTelegramClient([chat], {})

        await run_scanner(client, db, scan_settings)

        assert client.count("GetParticipants") >= 1
        assert {lead.username for lead in await leads_in(db)} == {"first_tag", "second_tag"}

    async def test_roster_skipped_when_disabled(self, db, scan_settings):
        scan_settings.collect_roster = False
        chat = ChatFixture(
            entity=make_channel(1001),
            participants=[make_user(50, "first_tag")],
        )
        client = FakeTelegramClient([chat], {})

        await run_scanner(client, db, scan_settings)
        assert client.count("GetParticipants") == 0

    async def test_basic_group_uses_preloaded_participants(self, db, scan_settings):
        """У обычных групп участники приходят с метаданными, повтор не нужен."""
        scan_settings.collect_roster = True
        chat = ChatFixture(
            entity=make_basic_group(2001),
            participants=[make_user(60, "group_one"), make_user(61, "group_two")],
        )
        client = FakeTelegramClient([chat], {})

        await run_scanner(client, db, scan_settings)

        assert client.count("GetParticipants") == 0
        assert {lead.username for lead in await leads_in(db)} == {"group_one", "group_two"}


class TestChannels:
    async def test_comments_collected_from_linked_chat(self, db, scan_settings):
        users = {1: make_user(1, "commenter")}
        discussion = ChatFixture(
            entity=make_channel(3002, "Обсуждение"),
            messages=[make_message(11, 1, text="а сколько стоит?")],
        )
        channel = ChatFixture(
            entity=make_channel(3001, "Канал", megagroup=False, broadcast=True),
            linked_chat_id=get_peer_id(discussion.entity),
        )
        client = FakeTelegramClient([channel, discussion], users)

        await run_scanner(client, db, scan_settings)

        stored = await leads_in(db)
        assert stored[0].username == "commenter"
        assert stored[0].source == SourceKind.COMMENT.value

    async def test_channel_without_discussion_is_reported(self, db, scan_settings):
        channel = ChatFixture(
            entity=make_channel(3001, "Канал", megagroup=False, broadcast=True),
            linked_chat_id=None,
        )
        report = await run_scanner(FakeTelegramClient([channel], {}), db, scan_settings)

        assert "обсужд" in report.chats[0].skipped

    async def test_comments_disabled(self, db, scan_settings):
        scan_settings.collect_comments = False
        discussion = ChatFixture(entity=make_channel(3002), messages=[])
        channel = ChatFixture(
            entity=make_channel(3001, megagroup=False, broadcast=True),
            linked_chat_id=get_peer_id(discussion.entity),
        )
        report = await run_scanner(
            FakeTelegramClient([channel, discussion], {}), db, scan_settings
        )

        channel_report = next(c for c in report.chats if c.chat_id == channel.peer_id)
        assert channel_report.skipped is not None


class TestForums:
    async def test_excluded_topic_is_skipped(self, db, scan_settings):
        scan_settings.excluded_topic_titles = ["флуд"]
        users = {1: make_user(1, "work_tag"), 2: make_user(2, "flood_tag")}
        forum = ChatFixture(
            entity=make_channel(4001, "Форум", forum=True),
            topics=[(10, "Работа", 30), (20, "Флудилка", 29)],
            messages=[
                make_message(30, 1, topic_id=10),
                make_message(29, 2, topic_id=20),
            ],
        )
        await run_scanner(FakeTelegramClient([forum], users), db, scan_settings)

        assert {lead.username for lead in await leads_in(db)} == {"work_tag"}

    async def test_all_topics_by_default(self, db, scan_settings):
        users = {1: make_user(1, "one_tag"), 2: make_user(2, "two_tag")}
        forum = ChatFixture(
            entity=make_channel(4001, forum=True),
            topics=[(10, "Работа", 30), (20, "Вопросы", 29)],
            messages=[
                make_message(30, 1, topic_id=10),
                make_message(29, 2, topic_id=20),
            ],
        )
        await run_scanner(FakeTelegramClient([forum], users), db, scan_settings)
        assert len(await leads_in(db)) == 2

    async def test_busiest_topic_only(self, db, scan_settings):
        scan_settings.forum_busiest_topic_only = True
        users = {1: make_user(1, "busy_tag"), 2: make_user(2, "quiet_tag")}
        forum = ChatFixture(
            entity=make_channel(4001, forum=True),
            topics=[(10, "Активный", 900), (20, "Тихий", 100)],
            messages=[
                make_message(30, 1, topic_id=10),
                make_message(29, 2, topic_id=20),
            ],
        )
        await run_scanner(FakeTelegramClient([forum], users), db, scan_settings)

        assert {lead.username for lead in await leads_in(db)} == {"busy_tag"}

    async def test_topic_title_recorded(self, db, scan_settings):
        users = {1: make_user(1, "work_tag")}
        forum = ChatFixture(
            entity=make_channel(4001, forum=True),
            topics=[(10, "Вакансии", 30)],
            messages=[make_message(30, 1, topic_id=10)],
        )
        await run_scanner(FakeTelegramClient([forum], users), db, scan_settings)

        assert (await leads_in(db))[0].topic_title == "Вакансии"


class TestArchiveForwarding:
    async def test_untagged_user_is_forwarded(self, db, scan_settings):
        users = {1: make_user(1, username=None, first_name="Безтегов")}
        chat = ChatFixture(entity=make_channel(1001), messages=[make_message(42, 1)])
        client = FakeTelegramClient([chat], users)

        report = await run_scanner(client, db, scan_settings)

        assert client.created_channels == 1
        assert client.forwarded == [(chat.peer_id, 42)]
        assert report.forwarded == 1
        stored = await leads_in(db)
        assert stored[0].archive_link is not None
        assert stored[0].archive_anonymized is False

    async def test_tagged_user_is_not_forwarded(self, db, scan_settings):
        users = {1: make_user(1, "has_tag")}
        chat = ChatFixture(entity=make_channel(1001), messages=[make_message(42, 1)])
        client = FakeTelegramClient([chat], users)

        await run_scanner(client, db, scan_settings)

        assert client.forwarded == []
        assert client.created_channels == 0

    async def test_hidden_forward_author_is_flagged(self, db, scan_settings):
        """Приватность «пересылки — никто» убирает ссылку на автора из карточки."""
        users = {1: make_user(1, username=None)}
        chat = ChatFixture(
            entity=make_channel(1001),
            messages=[make_message(42, 1)],
            forward_anonymized=True,
        )
        report = await run_scanner(FakeTelegramClient([chat], users), db, scan_settings)

        stored = await leads_in(db)
        assert stored[0].archive_anonymized is True
        assert stored[0].message_link is not None  # запасная ссылка на оригинал
        assert report.anonymized == 1

    async def test_forward_restriction_does_not_lose_the_lead(self, db, scan_settings):
        users = {1: make_user(1, username=None)}
        chat = ChatFixture(
            entity=make_channel(1001),
            messages=[make_message(42, 1)],
            forward_error=ChatForwardsRestrictedError(request=None),
        )
        report = await run_scanner(FakeTelegramClient([chat], users), db, scan_settings)

        stored = await leads_in(db)
        assert len(stored) == 1
        assert stored[0].archive_link is None
        assert stored[0].message_link is not None
        assert report.forwarded == 0

    async def test_forwarding_can_be_disabled(self, db, scan_settings):
        scan_settings.forward_untagged = False
        users = {1: make_user(1, username=None)}
        chat = ChatFixture(entity=make_channel(1001), messages=[make_message(42, 1)])
        client = FakeTelegramClient([chat], users)

        await run_scanner(client, db, scan_settings)

        assert client.forwarded == []
        assert len(await leads_in(db)) == 1

    async def test_channel_created_once_for_many_users(self, db, scan_settings):
        users = {i: make_user(i, username=None) for i in range(1, 6)}
        chat = ChatFixture(
            entity=make_channel(1001),
            messages=[make_message(50 - i, i) for i in range(1, 6)],
        )
        client = FakeTelegramClient([chat], users)

        await run_scanner(client, db, scan_settings)

        assert client.created_channels == 1
        assert len(client.forwarded) == 5


class TestFloodHandling:
    async def test_peer_flood_aborts_and_flags(self, db, scan_settings):
        users = {1: make_user(1, "alpha_tag")}
        chat = ChatFixture(entity=make_channel(1001), messages=[make_message(9, 1)])
        client = FakeTelegramClient([chat], users)

        original = client._history

        def explode(request):
            raise PeerFloodError(request=None)

        client._history = explode

        report = await run_scanner(client, db, scan_settings)

        assert report.aborted is True
        assert report.flagged is True
        assert "PeerFlood" in report.abort_reason
        client._history = original

    async def test_scan_continues_after_single_chat_error(self, db, scan_settings):
        users = {1: make_user(1, "alpha_tag"), 2: make_user(2, "beta_tag")}
        broken = ChatFixture(entity=make_channel(1001, "Сломанный"))
        good = ChatFixture(entity=make_channel(1002, "Рабочий"), messages=[make_message(9, 2)])
        client = FakeTelegramClient([broken, good], users)

        report = await run_scanner(client, db, scan_settings)

        assert report.new_leads == 1
        assert len(report.chats) == 2


class TestCheckpoints:
    async def test_progress_is_saved(self, db, scan_settings):
        users = {1: make_user(1, "alpha_tag")}
        chat = ChatFixture(entity=make_channel(1001), messages=[make_message(42, 1)])
        await run_scanner(FakeTelegramClient([chat], users), db, scan_settings)

        async with db.session() as session:
            from sqlalchemy import select

            state = await session.scalar(select(ChatState))
        assert state.oldest_message_id == 42
        assert state.history_done is True
        assert state.participants_visible is True

    async def test_finished_chat_is_not_rescanned(self, db, scan_settings):
        users = {1: make_user(1, "alpha_tag")}
        chat = ChatFixture(entity=make_channel(1001), messages=[make_message(42, 1)])

        await run_scanner(FakeTelegramClient([chat], users), db, scan_settings)
        second_client = FakeTelegramClient([chat], users)
        await run_scanner(second_client, db, scan_settings)

        assert second_client.count("GetHistory") == 0

    async def test_reset_allows_rescan(self, db, scan_settings):
        from tgparser.db.repo import ChatStateRepo

        users = {1: make_user(1, "alpha_tag")}
        chat = ChatFixture(entity=make_channel(1001), messages=[make_message(42, 1)])
        await run_scanner(FakeTelegramClient([chat], users), db, scan_settings)

        async with db.session() as session:
            await ChatStateRepo(session).reset(1)

        second_client = FakeTelegramClient([chat], users)
        await run_scanner(second_client, db, scan_settings)
        assert second_client.count("GetHistory") >= 1


class TestPagination:
    @pytest.mark.parametrize("total", [1, 99, 100, 101, 250])
    async def test_all_messages_are_walked(self, db, scan_settings, total):
        users = {i: make_user(i, f"user_{i:04d}") for i in range(1, total + 1)}
        chat = ChatFixture(
            entity=make_channel(1001),
            messages=[make_message(total + 1 - i, i) for i in range(1, total + 1)],
        )
        client = FakeTelegramClient([chat], users)

        report = await run_scanner(client, db, scan_settings)

        assert report.new_leads == total
        assert report.scanned_messages == total

    async def test_batch_size_controls_request_count(self, db, scan_settings):
        scan_settings.history_batch_size = 10
        users = {i: make_user(i, f"user_{i:04d}") for i in range(1, 51)}
        chat = ChatFixture(
            entity=make_channel(1001),
            messages=[make_message(51 - i, i) for i in range(1, 51)],
        )
        client = FakeTelegramClient([chat], users)

        await run_scanner(client, db, scan_settings)

        # Пять полных страниц плюс один запрос, который возвращает пусто:
        # конец истории виден только по короткому ответу.
        assert client.count("GetHistory") == 6
