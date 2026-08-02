"""Общий контекст, который прокидывается в обработчики."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from tgparser.bot.scan_service import ScanService
from tgparser.config import Settings
from tgparser.crypto import SessionCipher
from tgparser.userbot.auth import AuthManager


@dataclass(slots=True)
class BotContext:
    app_settings: Settings
    db: Any
    cipher: SessionCipher
    auth: AuthManager
    scan: ScanService

    async def has_account(self, owner_id: int) -> bool:
        from tgparser.db.repo import AccountRepo

        async with self.db.session() as session:
            return await AccountRepo(session, owner_id).first_active() is not None
