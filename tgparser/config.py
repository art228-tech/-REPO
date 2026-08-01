"""Настройки уровня процесса (читаются из окружения / .env)."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    bot_token: str = Field(default="", alias="BOT_TOKEN")
    api_id: int = Field(default=0, alias="API_ID")
    api_hash: str = Field(default="", alias="API_HASH")

    # Ключ Fernet для шифрования session string в БД.
    session_encryption_key: str = Field(default="", alias="SESSION_ENCRYPTION_KEY")

    # Telegram user id владельца бота. Остальные к боту не допускаются.
    owner_id: int = Field(default=0, alias="OWNER_ID")

    db_path: Path = Field(default=PROJECT_ROOT / "data" / "tgparser.sqlite3", alias="DB_PATH")
    export_dir: Path = Field(default=PROJECT_ROOT / "data" / "exports", alias="EXPORT_DIR")

    # Отпечаток клиента: чем ближе к реальному приложению, тем меньше внимания антиспама.
    device_model: str = Field(default="Desktop", alias="DEVICE_MODEL")
    system_version: str = Field(default="Windows 10", alias="SYSTEM_VERSION")
    app_version: str = Field(default="5.7.1", alias="APP_VERSION")

    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    @field_validator("db_path", "export_dir", mode="after")
    @classmethod
    def _expand(cls, value: Path) -> Path:
        return value.expanduser()

    def ensure_dirs(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.export_dir.mkdir(parents=True, exist_ok=True)

    @property
    def db_url(self) -> str:
        return f"sqlite+aiosqlite:///{self.db_path}"

    def missing_required(self) -> list[str]:
        """Список незаполненных обязательных переменных окружения."""
        missing = []
        if not self.bot_token:
            missing.append("BOT_TOKEN")
        if not self.api_id:
            missing.append("API_ID")
        if not self.api_hash:
            missing.append("API_HASH")
        if not self.owner_id:
            missing.append("OWNER_ID")
        if not self.session_encryption_key:
            missing.append("SESSION_ENCRYPTION_KEY")
        return missing


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings_cache() -> None:
    """Сброс кеша — нужен тестам."""
    global _settings
    _settings = None
