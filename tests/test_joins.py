"""Разбор служебных сообщений о вступлении.

Учитываются только три действия, которые формирует сам Telegram. Логи
вступлений от сторонних ботов сюда не относятся: там автор — бот, и такое
сообщение обычным текстом ничем от прочих не отличается.
"""

from __future__ import annotations

from tests.factories import (
    make_added,
    make_joined_by_link,
    make_joined_by_request,
    make_left,
    make_message,
    make_service_message,
)
from tgparser.core.joins import is_join, joiner_ids


class TestIsJoin:
    def test_recognises_add(self):
        assert is_join(make_added(1, 99, [5])) is True

    def test_recognises_link(self):
        assert is_join(make_joined_by_link(1, 5)) is True

    def test_recognises_request(self):
        assert is_join(make_joined_by_request(1, 5)) is True

    def test_leaving_is_not_a_join(self):
        assert is_join(make_left(1, 5)) is False

    def test_plain_message_is_not_a_join(self):
        assert is_join(make_message(1, 5)) is False

    def test_service_without_action(self):
        assert is_join(make_service_message(1, 5)) is False


class TestJoinerIds:
    def test_added_users_come_from_the_action(self):
        """При добавлении вступившие перечислены в действии, а не автор."""
        assert joiner_ids(make_added(1, adder_id=99, added_ids=[5, 6])) == [5, 6]

    def test_link_join_uses_the_author(self):
        assert joiner_ids(make_joined_by_link(1, user_id=7)) == [7]

    def test_request_join_uses_the_author(self):
        assert joiner_ids(make_joined_by_request(1, user_id=8)) == [8]

    def test_leaving_yields_nobody(self):
        assert joiner_ids(make_left(1, 9)) == []

    def test_plain_message_yields_nobody(self):
        assert joiner_ids(make_message(1, 9)) == []

    def test_empty_add_list(self):
        assert joiner_ids(make_added(1, 99, [])) == []
