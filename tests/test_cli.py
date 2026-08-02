"""Проверка команд `python -m tgparser`.

Команды печатают поля настроек, поэтому легко отстают от изменений схемы:
после переезда на многопользовательский режим `check` падал на исчезнувшем
поле. Эти тесты ловят такое.
"""

from __future__ import annotations

import pytest

from tgparser import __main__ as cli
from tgparser.config import reset_settings_cache

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
)


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch, tmp_path):
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    reset_settings_cache()
    yield
    reset_settings_cache()


def fill(monkeypatch, tmp_path, **extra):
    monkeypatch.setenv("BOT_TOKEN", "123:token")
    monkeypatch.setenv("SESSION_ENCRYPTION_KEY", "key")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "db.sqlite3"))
    monkeypatch.setenv("EXPORT_DIR", str(tmp_path / "exports"))
    for name, value in extra.items():
        monkeypatch.setenv(name, value)
    reset_settings_cache()


class TestGenkey:
    def test_prints_usable_key(self, capsys):
        assert cli.main(["genkey"]) == 0
        printed = capsys.readouterr().out.strip()

        from tgparser.crypto import SessionCipher

        cipher = SessionCipher(printed)
        assert cipher.decrypt(cipher.encrypt("секрет")) == "секрет"

    def test_keys_differ_between_calls(self, capsys):
        cli.main(["genkey"])
        first = capsys.readouterr().out.strip()
        cli.main(["genkey"])
        assert capsys.readouterr().out.strip() != first


class TestCheck:
    def test_reports_missing(self, capsys):
        assert cli.main(["check"]) == 1
        assert "Не заданы" in capsys.readouterr().out

    def test_passes_when_filled(self, monkeypatch, tmp_path, capsys):
        fill(monkeypatch, tmp_path)
        assert cli.main(["check"]) == 0
        out = capsys.readouterr().out
        assert "Конфигурация заполнена" in out

    def test_shows_open_access(self, monkeypatch, tmp_path, capsys):
        fill(monkeypatch, tmp_path)
        cli.main(["check"])
        assert "Доступ: открытый" in capsys.readouterr().out

    def test_shows_allowlist_size(self, monkeypatch, tmp_path, capsys):
        fill(monkeypatch, tmp_path, ACCESS_MODE="allowlist", ALLOWED_USER_IDS="1,2,3")
        cli.main(["check"])
        assert "3 id" in capsys.readouterr().out

    def test_reports_missing_allowlist(self, monkeypatch, tmp_path, capsys):
        fill(monkeypatch, tmp_path, ACCESS_MODE="allowlist")
        assert cli.main(["check"]) == 1
        assert "ALLOWED_USER_IDS" in capsys.readouterr().out

    def test_shows_per_user_keys_by_default(self, monkeypatch, tmp_path, capsys):
        fill(monkeypatch, tmp_path)
        cli.main(["check"])
        assert "у каждого свои" in capsys.readouterr().out

    def test_shows_shared_keys(self, monkeypatch, tmp_path, capsys):
        fill(monkeypatch, tmp_path, API_ID="12345", API_HASH="hash")
        cli.main(["check"])
        assert "общие из окружения" in capsys.readouterr().out

    def test_shows_admin(self, monkeypatch, tmp_path, capsys):
        fill(monkeypatch, tmp_path, ADMIN_ID="555")
        cli.main(["check"])
        assert "Администратор: 555" in capsys.readouterr().out

    def test_hides_admin_when_unset(self, monkeypatch, tmp_path, capsys):
        fill(monkeypatch, tmp_path)
        cli.main(["check"])
        assert "Администратор" not in capsys.readouterr().out


class TestLogFile:
    """Логи должны переживать пересборку контейнера.

    `docker compose logs` показывает только текущий контейнер, а разбираться
    с прошлыми прогонами приходится именно по истории.
    """

    def test_log_file_sits_next_to_the_database(self, monkeypatch, tmp_path):
        from tgparser.config import get_settings

        fill(monkeypatch, tmp_path)
        settings = get_settings()
        assert settings.log_file.parent == settings.db_path.parent
        assert settings.log_file.name.endswith(".log")

    def test_configure_logging_writes_to_the_file(self, tmp_path):
        import logging

        target = tmp_path / "logs" / "tgparser.log"
        root = logging.getLogger()
        saved = root.handlers[:]
        try:
            cli._configure_logging("INFO", target)
            logging.getLogger("tgparser.test").info("проверочная запись")
            for handler in logging.getLogger().handlers:
                handler.flush()
            assert target.exists()
            assert "проверочная запись" in target.read_text(encoding="utf-8")
        finally:
            for handler in logging.getLogger().handlers[:]:
                handler.close()
                logging.getLogger().removeHandler(handler)
            for handler in saved:
                root.addHandler(handler)

    def test_logging_works_without_a_file(self):
        import logging

        root = logging.getLogger()
        saved = root.handlers[:]
        try:
            cli._configure_logging("INFO", None)
            assert logging.getLogger().handlers
        finally:
            for handler in logging.getLogger().handlers[:]:
                logging.getLogger().removeHandler(handler)
            for handler in saved:
                root.addHandler(handler)


class TestArgs:
    def test_unknown_command_exits(self):
        with pytest.raises(SystemExit):
            cli.main(["nonsense"])

    def test_default_command_is_run(self, monkeypatch):
        called: list[str] = []

        def fake_run() -> int:
            called.append("run")
            return 0

        monkeypatch.setattr(cli, "cmd_run", fake_run)
        assert cli.main([]) == 0
        assert called == ["run"]
