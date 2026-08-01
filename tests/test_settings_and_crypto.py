from __future__ import annotations

import json

import pytest

from tgparser.crypto import SessionCipher, SessionCipherError, generate_key
from tgparser.db.settings_store import (
    Pace,
    ScanSettings,
    load_settings,
    save_settings,
)

OWNER_A = 1001
OWNER_B = 2002


class TestScanSettingsSerialization:
    def test_round_trip(self):
        original = ScanSettings(history_depth_days=90, collect_roster=True)
        restored = ScanSettings.from_json(original.to_json())
        assert restored.history_depth_days == 90
        assert restored.collect_roster is True

    def test_unknown_keys_are_ignored(self):
        raw = json.dumps({"history_depth_days": 7, "legacy_option": True})
        restored = ScanSettings.from_json(raw)
        assert restored.history_depth_days == 7

    def test_missing_keys_fall_back_to_defaults(self):
        restored = ScanSettings.from_json("{}")
        assert restored.history_depth_days == 30
        assert restored.collect_history is True

    def test_cyrillic_survives_round_trip(self):
        original = ScanSettings(excluded_topic_titles=["флуд", "оффтоп"])
        restored = ScanSettings.from_json(original.to_json())
        assert restored.excluded_topic_titles == ["флуд", "оффтоп"]


class TestDefaults:
    def test_roster_is_off_by_default(self):
        """Перебор участников — главный триггер PeerFlood, включается вручную."""
        assert ScanSettings().collect_roster is False

    def test_history_and_comments_on_by_default(self):
        settings = ScanSettings()
        assert settings.collect_history is True
        assert settings.collect_comments is True

    def test_roster_budget_is_tighter_than_history(self):
        settings = ScanSettings()
        assert settings.roster_calls_per_hour < settings.history_calls_per_hour

    def test_all_topics_by_default(self):
        assert ScanSettings().forum_busiest_topic_only is False


class TestPace:
    """Разгон считается по числу успешных запросов, а не по прогонам.

    Регресс: раньше счётчик рос только у прогона, доведённого до конца, а
    полный обход большого набора чатов идёт сутками — из-за этого темп
    оставался пониженным навсегда.
    """

    def test_fresh_account_is_throttled(self):
        pace = Pace(ScanSettings(), calls_done=0)
        assert pace.in_warmup is True
        assert pace.throttled is True

    def test_warmup_lowers_budgets(self):
        settings = ScanSettings(
            roster_calls_per_hour=20, history_calls_per_hour=240, write_calls_per_hour=120
        )
        pace = Pace(settings, calls_done=0)
        assert pace.roster == 5
        assert pace.history == 60
        assert pace.write == 30

    def test_full_budget_after_enough_calls(self):
        settings = ScanSettings(warmup_calls_required=200)
        pace = Pace(settings, calls_done=200)
        assert pace.in_warmup is False
        assert pace.throttled is False
        assert pace.history == settings.history_calls_per_hour
        assert pace.roster == settings.roster_calls_per_hour

    def test_partial_progress_still_throttled(self):
        pace = Pace(ScanSettings(warmup_calls_required=200), calls_done=199)
        assert pace.throttled is True

    def test_flood_events_keep_budget_down(self):
        """Если Telegram уже присылал FloodWait, темп повышать бессмысленно."""
        pace = Pace(ScanSettings(), calls_done=100_000, flood_events=1)
        assert pace.in_warmup is False
        assert pace.throttled is True
        assert pace.history < pace.settings.history_calls_per_hour

    def test_budget_never_drops_to_zero(self):
        pace = Pace(
            ScanSettings(roster_calls_per_hour=1, warmup_factor=0.01), calls_done=0
        )
        assert pace.roster >= 1
        assert pace.history >= 30

    def test_reason_mentions_progress(self):
        pace = Pace(ScanSettings(warmup_calls_required=200), calls_done=50)
        assert "50" in pace.reason
        assert "200" in pace.reason

    def test_reason_mentions_flood(self):
        pace = Pace(ScanSettings(), calls_done=100_000, flood_events=3)
        assert "FloodWait" in pace.reason

    def test_no_reason_at_full_speed(self):
        assert Pace(ScanSettings(), calls_done=100_000).reason is None


class TestSettingsStore:
    async def test_defaults_when_empty(self, db):
        async with db.session() as session:
            settings = await load_settings(session, OWNER_A)
        assert settings.history_depth_days == 30

    async def test_save_and_load(self, db):
        async with db.session() as session:
            settings = await load_settings(session, OWNER_A)
            settings.history_depth_days = 7
            settings.excluded_chats = ["@spam"]
            await save_settings(session, OWNER_A, settings)

        async with db.session() as session:
            restored = await load_settings(session, OWNER_A)
        assert restored.history_depth_days == 7
        assert restored.excluded_chats == ["@spam"]

    async def test_overwrites_existing_row(self, db):
        async with db.session() as session:
            await save_settings(session, OWNER_A, ScanSettings(history_depth_days=7))
            await save_settings(session, OWNER_A, ScanSettings(history_depth_days=14))

        async with db.session() as session:
            assert (await load_settings(session, OWNER_A)).history_depth_days == 14

    async def test_corrupted_value_falls_back(self, db):
        from tgparser.db.models import Setting
        from tgparser.db.settings_store import SETTINGS_KEY

        async with db.session() as session:
            session.add(Setting(owner_id=OWNER_A, key=SETTINGS_KEY, value="не json"))

        async with db.session() as session:
            assert (await load_settings(session, OWNER_A)).history_depth_days == 30


class TestSessionCipher:
    def test_round_trip(self):
        cipher = SessionCipher(generate_key())
        secret = "1BVtsOK4Bu...session"
        assert cipher.decrypt(cipher.encrypt(secret)) == secret

    def test_ciphertext_differs_from_plaintext(self):
        cipher = SessionCipher(generate_key())
        assert b"session" not in cipher.encrypt("my-session-string")

    def test_empty_key_rejected(self):
        with pytest.raises(SessionCipherError, match="SESSION_ENCRYPTION_KEY"):
            SessionCipher("")

    def test_malformed_key_rejected(self):
        with pytest.raises(SessionCipherError, match="Некорректный"):
            SessionCipher("не-ключ")

    def test_wrong_key_cannot_decrypt(self):
        token = SessionCipher(generate_key()).encrypt("секрет")
        with pytest.raises(SessionCipherError, match="ключ не совпадает"):
            SessionCipher(generate_key()).decrypt(token)
