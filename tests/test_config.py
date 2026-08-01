from __future__ import annotations

import pytest

from tgparser.config import Settings

ENV_VARS = (
    "BOT_TOKEN",
    "API_ID",
    "API_HASH",
    "OWNER_ID",
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
        "OWNER_ID": 999,
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
    def test_blank_owner_id_does_not_raise(self, blank):
        assert build(OWNER_ID=blank).owner_id == 0

    def test_blank_values_are_reported_as_missing(self):
        settings = build(API_ID="", OWNER_ID="", BOT_TOKEN="")
        assert set(settings.missing_required()) == {"API_ID", "OWNER_ID", "BOT_TOKEN"}

    def test_real_values_still_parse(self):
        assert build(API_ID="12345").api_id == 12345

    def test_garbage_still_rejected(self):
        with pytest.raises(ValueError, match="API_ID"):
            build(API_ID="не число")


class TestMissingRequired:
    def test_nothing_missing_when_filled(self):
        assert build().missing_required() == []

    def test_lists_every_empty_field(self):
        settings = Settings(_env_file=None)
        assert set(settings.missing_required()) == {
            "BOT_TOKEN",
            "API_ID",
            "API_HASH",
            "OWNER_ID",
            "SESSION_ENCRYPTION_KEY",
        }


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
