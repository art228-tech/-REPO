from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from tgparser.core.util import (
    chat_matches,
    cutoff_datetime,
    extract_usernames,
    humanize_seconds,
    is_topic_excluded,
    message_link,
    normalize_username,
    snippet,
    strip_channel_prefix,
)


class TestStripChannelPrefix:
    def test_marked_id(self):
        assert strip_channel_prefix(-1001234567890) == 1234567890

    def test_plain_positive(self):
        assert strip_channel_prefix(1234567890) == 1234567890

    def test_basic_group_negative(self):
        assert strip_channel_prefix(-555) == 555


class TestMessageLink:
    def test_public_chat_uses_username(self):
        assert message_link(42, chat_username="mychat") == "https://t.me/mychat/42"

    def test_username_with_at_is_normalized(self):
        assert message_link(42, chat_username="@mychat") == "https://t.me/mychat/42"

    def test_private_chat_uses_internal_id(self):
        assert message_link(7, chat_id=-1001234567890) == "https://t.me/c/1234567890/7"

    def test_username_wins_over_id(self):
        link = message_link(7, chat_id=-1001234567890, chat_username="pub")
        assert link == "https://t.me/pub/7"

    def test_forum_topic_included(self):
        link = message_link(9, chat_id=-1001234567890, topic_id=5)
        assert link == "https://t.me/c/1234567890/5/9"

    def test_no_target_returns_none(self):
        assert message_link(9) is None

    def test_invalid_message_id(self):
        assert message_link(0, chat_username="pub") is None


class TestCutoff:
    def test_zero_means_no_limit(self):
        assert cutoff_datetime(0) is None

    def test_negative_means_no_limit(self):
        assert cutoff_datetime(-5) is None

    def test_subtracts_days(self):
        now = datetime(2026, 8, 1, tzinfo=UTC)
        assert cutoff_datetime(30, now=now) == now - timedelta(days=30)


class TestTopicExclusion:
    @pytest.mark.parametrize(
        "title",
        ["Флуд", "флудилка", "ОФФТОП", "Болталка и мемы"],
    )
    def test_matches_case_insensitively(self, title):
        assert is_topic_excluded(title, ["флуд", "оффтоп", "болталка"])

    def test_keeps_unrelated(self):
        assert not is_topic_excluded("Вакансии", ["флуд", "оффтоп"])

    def test_empty_inputs(self):
        assert not is_topic_excluded(None, ["флуд"])
        assert not is_topic_excluded("Флуд", [])
        assert not is_topic_excluded("Флуд", ["  "])


class TestChatMatches:
    def test_by_username(self):
        assert chat_matches(-1001, "MyChat", ["@mychat"])

    def test_by_username_without_at(self):
        assert chat_matches(-1001, "mychat", ["MyChat"])

    def test_by_marked_id(self):
        assert chat_matches(-1001234567890, None, ["-1001234567890"])

    def test_by_internal_id(self):
        assert chat_matches(-1001234567890, None, ["1234567890"])

    def test_no_match(self):
        assert not chat_matches(-1001, "mychat", ["@other", "-999"])

    def test_empty_list(self):
        assert not chat_matches(-1001, "mychat", [])

    def test_ignores_garbage_entries(self):
        assert not chat_matches(-1001, None, ["", "   "])


class TestNormalizeUsername:
    @pytest.mark.parametrize(
        "raw",
        ["@ivanov", "ivanov", "t.me/ivanov", "https://t.me/ivanov", "  @ivanov  "],
    )
    def test_accepts_forms(self, raw):
        assert normalize_username(raw) == "ivanov"

    def test_strips_query(self):
        assert normalize_username("https://t.me/ivanov?start=1") == "ivanov"

    @pytest.mark.parametrize("raw", ["", "@ab", "1abc", "с_кириллицей", "a" * 40, "@@x"])
    def test_rejects_invalid(self, raw):
        assert normalize_username(raw) is None

    def test_length_boundaries(self):
        assert normalize_username("abc") is None
        assert normalize_username("abcd") == "abcd"
        assert normalize_username("a" * 32) == "a" * 32
        assert normalize_username("a" * 33) is None


class TestExtractUsernames:
    def test_splits_on_separators(self):
        text = "@alpha beta, gamma\n@delta"
        assert extract_usernames(text) == ["alpha", "beta", "gamma", "delta"]

    def test_dedupes_case_insensitively(self):
        assert extract_usernames("@Ivanov @ivanov IVANOV") == ["Ivanov"]

    def test_drops_invalid(self):
        assert extract_usernames("@valid 1bad кириллица abc") == ["valid"]

    def test_mixed_links_and_tags(self):
        text = "https://t.me/first\n@second\nt.me/third"
        assert extract_usernames(text) == ["first", "second", "third"]

    def test_empty(self):
        assert extract_usernames("") == []


class TestSnippet:
    def test_collapses_whitespace(self):
        assert snippet("а  б\n\nв") == "а б в"

    def test_truncates_with_ellipsis(self):
        result = snippet("я" * 500, limit=10)
        assert len(result) == 10
        assert result.endswith("…")

    def test_empty_returns_none(self):
        assert snippet("") is None
        assert snippet(None) is None
        assert snippet("   ") is None


class TestHumanizeSeconds:
    @pytest.mark.parametrize(
        ("seconds", "expected"),
        [(5, "5 с"), (65, "1 мин 5 с"), (3700, "1 ч 1 мин")],
    )
    def test_formats(self, seconds, expected):
        assert humanize_seconds(seconds) == expected
