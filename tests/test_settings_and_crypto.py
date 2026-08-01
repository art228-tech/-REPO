from __future__ import annotations

import json

import pytest

from tgparser.crypto import SessionCipher, SessionCipherError, generate_key
from tgparser.db.settings_store import ScanSettings, load_settings, save_settings

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


class TestWarmup:
    def test_new_install_is_in_warmup(self):
        assert ScanSettings().in_warmup is True

    def test_warmup_lowers_budgets(self):
        settings = ScanSettings(roster_calls_per_hour=20, history_calls_per_hour=240)
        assert settings.effective_roster_budget() == 5
        assert settings.effective_history_budget() == 60

    def test_full_budget_after_warmup(self):
        settings = ScanSettings(warmup_runs_done=3, warmup_runs_required=3)
        assert settings.in_warmup is False
        assert settings.effective_roster_budget() == settings.roster_calls_per_hour

    def test_budget_never_drops_to_zero(self):
        settings = ScanSettings(roster_calls_per_hour=1, warmup_factor=0.01)
        assert settings.effective_roster_budget() >= 1


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
