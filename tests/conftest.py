from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from videobot.db import Base  # noqa: E402


@pytest.fixture
def base(tmp_path: Path) -> Base:
    return Base(tmp_path / "bot.sqlite3")


def video_data(**kwargs) -> dict:
    data = {
        "duration_s": 14.3,
        "background": "blur",
        "voice_folder": "обыч",
        "music": True,
        "qr_s": 2.5,
    }
    data.update(kwargs)
    return data
