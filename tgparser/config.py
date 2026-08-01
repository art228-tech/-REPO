"""Настройки уровня процесса (читаются из окружения / .env)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

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

    # Необязательные общие ключи приложения. Если пусто, каждый пользователь
    # получает свои при подключении аккаунта — через my.telegram.org
    # автоматически либо вводит руками.
    api_id: int = Field(default=0, alias="API_ID")
    api_hash: str = Field(default="", alias="API_HASH")

    # Ключ Fernet для шифрования session string в БД.
    session_encryption_key: str = Field(default="", alias="SESSION_ENCRYPTION_KEY")

    # open — бот доступен любому, allowlist — только id из allowed_user_ids.
    access_mode: Literal["open", "allowlist"] = Field(default="open", alias="ACCESS_MODE")
    allowed_user_ids: list[int] = Field(default_factory=list, alias="ALLOWED_USER_IDS")

    # Необязательный администратор: видит сводку по всем пользователям.
    admin_id: int = Field(default=0, alias="ADMIN_ID")

    db_path: Path = Field(default=PROJECT_ROOT / "data" / "tgparser.sqlite3", alias="DB_PATH")
    export_dir: Path = Field(default=PROJECT_ROOT / "data" / "exports", alias="EXPORT_DIR")

    # Отпечаток клиента: чем ближе к реальному приложению, тем меньше внимания антиспама.
    device_model: str = Field(default="Desktop", alias="DEVICE_MODEL")
    system_version: str = Field(default="Windows 10", alias="SYSTEM_VERSION")
    app_version: str = Field(default="5.7.1", alias="APP_VERSION")

    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    @field_validator("api_id", "admin_id", mode="before")
    @classmethod
    def _blank_is_zero(cls, value: object) -> object:
        """Пустое значение в .env — это «не заполнено», а не ошибка типа.

        Иначе шаблон с `API_ID=` роняет конструктор раньше, чем отработает
        проверка обязательных полей, и вместо понятного списка недостающих
        переменных пользователь видит трейсбек pydantic.
        """
        if isinstance(value, str) and not value.strip():
            return 0
        return value

    @field_validator("allowed_user_ids", mode="before")
    @classmethod
    def _parse_id_list(cls, value: object) -> object:
        """Список id приходит строкой вида `1,2,3`."""
        if isinstance(value, str):
            return [int(part) for part in value.replace(";", ",").split(",") if part.strip()]
        return value

    @field_validator("access_mode", mode="before")
    @classmethod
    def _normalize_mode(cls, value: object) -> object:
        if isinstance(value, str):
            cleaned = value.strip().lower()
            return cleaned or "open"
        return value

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
        if not self.session_encryption_key:
            missing.append("SESSION_ENCRYPTION_KEY")
        if self.access_mode == "allowlist" and not self.allowed_user_ids:
            missing.append("ALLOWED_USER_IDS")
        return missing

    @property
    def has_shared_keys(self) -> bool:
        return bool(self.api_id and self.api_hash)

    def is_allowed(self, user_id: int) -> bool:
        if self.access_mode == "allowlist":
            return user_id in self.allowed_user_ids
        return True

    def is_admin(self, user_id: int) -> bool:
        return bool(self.admin_id) and user_id == self.admin_id


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
