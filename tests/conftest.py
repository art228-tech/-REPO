import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from elevenlabs_voiceover import paths  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    """Держим тесты подальше от настоящей папки %APPDATA%."""
    root = tmp_path / "appdata"
    root.mkdir()

    monkeypatch.setattr(paths, "user_data_dir", lambda: root)
    monkeypatch.setattr(paths, "config_path", lambda: root / "config.json")
    monkeypatch.setattr(paths, "state_db_path", lambda: root / "state.sqlite3")

    logs = root / "logs"
    logs.mkdir(exist_ok=True)
    monkeypatch.setattr(paths, "logs_dir", lambda: logs)

    reports = root / "reports"
    reports.mkdir(exist_ok=True)
    monkeypatch.setattr(paths, "reports_dir", lambda: reports)

    # Модули импортировали функции по имени — подменяем и там.
    from elevenlabs_voiceover import config as config_module
    from elevenlabs_voiceover import state as state_module

    monkeypatch.setattr(config_module, "config_path", lambda: root / "config.json")
    monkeypatch.setattr(state_module, "state_db_path", lambda: root / "state.sqlite3")

    return root
