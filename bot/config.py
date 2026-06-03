"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv


@dataclass(frozen=True, slots=True)
class Config:
    """Runtime configuration for the bot."""

    bot_token: str
    admin_ids: frozenset[int] = field(default_factory=frozenset)
    db_path: str = "data/bot.sqlite3"

    def is_admin(self, user_id: int | None) -> bool:
        """Return True if the given user id has admin rights."""
        return user_id is not None and user_id in self.admin_ids


def _parse_admin_ids(raw: str | None) -> frozenset[int]:
    if not raw:
        return frozenset()
    ids: set[int] = set()
    for chunk in raw.replace(";", ",").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            ids.add(int(chunk))
        except ValueError as exc:  # pragma: no cover - defensive
            raise ValueError(f"Invalid admin id: {chunk!r}") from exc
    return frozenset(ids)


def load_config() -> Config:
    """Load and validate configuration from the environment / .env file."""
    load_dotenv()

    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError(
            "BOT_TOKEN is not set. Copy .env.example to .env and fill in the value."
        )

    return Config(
        bot_token=token,
        admin_ids=_parse_admin_ids(os.getenv("ADMIN_IDS")),
        db_path=os.getenv("DB_PATH", "data/bot.sqlite3").strip() or "data/bot.sqlite3",
    )
