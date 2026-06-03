"""Конфигурация автопостера — из .env."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

BOT_TOKEN: str = os.getenv("BOT_TOKEN", "").strip()

_admin_raw = os.getenv("ADMIN_IDS", "").strip()
ADMIN_IDS: list[int] = [
    int(x) for x in _admin_raw.replace(" ", "").split(",") if x
]

DB_PATH: str = os.getenv("DB_PATH", str(BASE_DIR / "data.db")).strip()

if not BOT_TOKEN:
    raise SystemExit("BOT_TOKEN не задан в .env")
if not ADMIN_IDS:
    raise SystemExit("ADMIN_IDS не заданы в .env")
