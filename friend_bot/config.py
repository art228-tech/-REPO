"""Конфигурация бота-конструктора. Все значения читаются из .env."""
import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _int_list(value: str) -> list[int]:
    return [int(x.strip()) for x in value.split(",") if x.strip()]


# Главный бот-конструктор
BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
ADMIN_IDS: list[int] = _int_list(os.getenv("ADMIN_IDS", ""))

# База данных
DB_PATH: str = os.getenv("DB_PATH", str(BASE_DIR / "data.db"))

# Веб-приложение (рулетка)
WEBAPP_URL: str = os.getenv("WEBAPP_URL", "").rstrip("/")
WEBAPP_HOST: str = os.getenv("WEBAPP_HOST", "0.0.0.0")
WEBAPP_PORT: int = int(os.getenv("WEBAPP_PORT", "8080"))

# Технические настройки
DEFAULT_DELETE_TIMER: int = 10
DEFAULT_DUPLICATE_AFTER: int = 60
DEFAULT_DUPLICATE_MAX: int = 3

# Лимиты рассылки
BROADCAST_RATE_PER_SECOND: int = 25  # сообщений в секунду

if not BOT_TOKEN:
    raise SystemExit("BOT_TOKEN не задан. Создай .env по образцу .env.example")
if not ADMIN_IDS:
    raise SystemExit("ADMIN_IDS не задан. Создай .env по образцу .env.example")
