from __future__ import annotations

import pytest

from tgparser.config import Settings

ENV_VARS = (
    "BOT_TOKEN",
    "API_ID",
    "API_HASH",
    "ADMIN_ID",
    "ACCESS_MODE",
    "ALLOWED_USER_IDS",
    "SESSION_ENCRYPTION_KEY",
    "DB_PATH",
    "EXPORT_DIR",
    "LOG_LEVEL",
)


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    """Результат не должен зависеть от того, что выставлено в окружении."""
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def build(**overrides) -> Settings:
    base = {
        "BOT_TOKEN": "123:token",
        "API_ID": 12345,
        "API_HASH": "hash",
        "SESSION_ENCRYPTION_KEY": "key",
        "_env_file": None,
    }
    base.update(overrides)
    return Settings(**base)


class TestBlankNumericFields:
    """Шаблон .env приходит с пустыми значениями — это не ошибка типа."""

    @pytest.mark.parametrize("blank", ["", "   "])
    def test_blank_api_id_does_not_raise(self, blank):
        assert build(API_ID=blank).api_id == 0

    @pytest.mark.parametrize("blank", ["", "   "])
    def test_blank_admin_id_does_not_raise(self, blank):
        assert build(ADMIN_ID=blank).admin_id == 0

    def test_blank_values_are_reported_as_missing(self):
        settings = build(BOT_TOKEN="", SESSION_ENCRYPTION_KEY="")
        assert set(settings.missing_required()) == {
            "BOT_TOKEN",
            "SESSION_ENCRYPTION_KEY",
        }

    def test_real_values_still_parse(self):
        assert build(API_ID="12345").api_id == 12345

    def test_garbage_still_rejected(self):
        with pytest.raises(ValueError, match="API_ID"):
            build(API_ID="не число")


class TestMissingRequired:
    def test_nothing_missing_when_filled(self):
        assert build().missing_required() == []

    def test_admin_is_optional(self):
        assert "ADMIN_ID" not in build(ADMIN_ID=0).missing_required()

    def test_lists_every_empty_field(self):
        settings = Settings(_env_file=None)
        assert set(settings.missing_required()) == {
            "BOT_TOKEN",
            "SESSION_ENCRYPTION_KEY",
        }

    def test_app_keys_are_optional(self):
        """Каждый пользователь может получить свои ключи при подключении."""
        settings = build(API_ID="", API_HASH="")
        assert settings.missing_required() == []
        assert settings.has_shared_keys is False

    def test_shared_keys_detected_when_present(self):
        assert build().has_shared_keys is True

    def test_allowlist_without_ids_is_incomplete(self):
        settings = build(ACCESS_MODE="allowlist", ALLOWED_USER_IDS="")
        assert "ALLOWED_USER_IDS" in settings.missing_required()


class TestAccessMode:
    def test_open_is_the_default(self):
        assert build().access_mode == "open"

    def test_open_lets_anyone_in(self):
        settings = build()
        assert settings.is_allowed(1) is True
        assert settings.is_allowed(999999) is True

    def test_allowlist_restricts(self):
        settings = build(ACCESS_MODE="allowlist", ALLOWED_USER_IDS="111,222")
        assert settings.is_allowed(111) is True
        assert settings.is_allowed(222) is True
        assert settings.is_allowed(333) is False

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("111,222", [111, 222]),
            ("111, 222 , 333", [111, 222, 333]),
            ("111;222", [111, 222]),
            ("111", [111]),
            ("", []),
        ],
    )
    def test_id_list_parsing(self, raw, expected):
        assert build(ALLOWED_USER_IDS=raw).allowed_user_ids == expected

    def test_mode_is_case_insensitive(self):
        assert build(ACCESS_MODE="OPEN").access_mode == "open"

    def test_blank_mode_falls_back_to_open(self):
        assert build(ACCESS_MODE="").access_mode == "open"

    def test_unknown_mode_rejected(self):
        with pytest.raises(ValueError, match="ACCESS_MODE"):
            build(ACCESS_MODE="whatever")


class TestAdmin:
    def test_no_admin_by_default(self):
        assert build().is_admin(1) is False

    def test_admin_recognised(self):
        settings = build(ADMIN_ID=555)
        assert settings.is_admin(555) is True
        assert settings.is_admin(556) is False

    def test_zero_is_not_an_admin(self):
        assert build(ADMIN_ID=0).is_admin(0) is False


class TestPaths:
    def test_db_url_points_at_db_path(self, tmp_path):
        settings = build(DB_PATH=tmp_path / "x.sqlite3")
        assert settings.db_url == f"sqlite+aiosqlite:///{tmp_path / 'x.sqlite3'}"

    def test_ensure_dirs_creates_both(self, tmp_path):
        settings = build(
            DB_PATH=tmp_path / "nested" / "db.sqlite3",
            EXPORT_DIR=tmp_path / "nested" / "exports",
        )
        settings.ensure_dirs()
        assert (tmp_path / "nested").is_dir()
        assert (tmp_path / "nested" / "exports").is_dir()

    def test_tilde_is_expanded(self):
        settings = build(DB_PATH="~/tgparser.sqlite3")
        assert not str(settings.db_path).startswith("~")
