from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")
load_dotenv()


def _env(key: str, default: str | None = None) -> str | None:
    value = os.getenv(key, default)
    return value if value not in ("", None) else default


DATA_DIR = Path(_env("DATA_DIR", str(BASE_DIR / "data"))).resolve()
SESSIONS_DIR = DATA_DIR / "sessions"
LOGS_DIR = DATA_DIR / "logs"
EXPORTS_DIR = DATA_DIR / "exports"
DB_PATH = DATA_DIR / "mailer.db"

BOT_TOKEN = _env("BOT_TOKEN", "")
API_ID = int(_env("API_ID", "0") or "0")
API_HASH = _env("API_HASH", "") or ""

LOG_LEVEL = _env("LOG_LEVEL", "INFO") or "INFO"
STATS_EDIT_INTERVAL_SEC = float(_env("STATS_EDIT_INTERVAL_SEC", "3") or "3")

for path in (DATA_DIR, SESSIONS_DIR, LOGS_DIR, EXPORTS_DIR):
    path.mkdir(parents=True, exist_ok=True)