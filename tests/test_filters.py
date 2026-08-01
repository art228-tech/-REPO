from __future__ import annotations

from tests.factories import make_channel, make_user
from tgparser.core.filters import (
    SKIP_BOT,
    SKIP_DELETED,
    SKIP_NOT_USER,
    SKIP_SEEN,
    SKIP_SELF,
    active_username,
    classify_user,
)


class TestActiveUsername:
    def test_plain_username(self):
        assert active_username(make_user(1, username="ivan")) == "ivan"

    def test_none_when_absent(self):
        assert active_username(make_user(1)) is None

    def test_prefers_active_from_collectible_list(self):
        user = make_user(
            1,
            username="old",
            usernames=[("retired", False), ("current", True)],
        )
        assert active_username(user) == "current"

    def test_falls_back_when_no_active_entry(self):
        user = make_user(1, username="main", usernames=[("retired", False)])
        assert active_username(user) == "main"


class TestClassifyUser:
    def test_accepts_regular_user(self):
        assert classify_user(make_user(10, username="ok")) is None

    def test_skips_bot(self):
        assert classify_user(make_user(10, bot=True)) is SKIP_BOT

    def test_keeps_bot_when_allowed(self):
        assert classify_user(make_user(10, bot=True), skip_bots=False) is None

    def test_skips_deleted(self):
        assert classify_user(make_user(10, deleted=True)) is SKIP_DELETED

    def test_keeps_deleted_when_allowed(self):
        assert classify_user(make_user(10, deleted=True), skip_deleted=False) is None

    def test_skips_self(self):
        assert classify_user(make_user(10), self_id=10) is SKIP_SELF

    def test_skips_already_seen(self):
        assert classify_user(make_user(10), seen={10}) is SKIP_SEEN

    def test_skips_channel_posing_as_sender(self):
        assert classify_user(make_channel(99)) is SKIP_NOT_USER

    def test_skips_none(self):
        assert classify_user(None) is SKIP_NOT_USER
