"""Создание Telethon-клиентов из сохранённых сессий."""

from __future__ import annotations

import logging

from telethon import TelegramClient
from telethon.sessions import StringSession

from tgparser.config import Settings
from tgparser.crypto import SessionCipher
from tgparser.db.models import Account
from tgparser.userbot.proxy import parse_proxy

logger = logging.getLogger(__name__)


def new_client(
    settings: Settings,
    session: str | StringSession | None = None,
    proxy: str | None = None,
) -> TelegramClient:
    """Клиент с отпечатком реального приложения.

    Значения device_model / system_version / app_version по умолчанию Telethon
    подставляет свои, и они заметно отличаются от официальных клиентов.
    """
    return TelegramClient(
        StringSession(session) if not isinstance(session, StringSession) else session,
        settings.api_id,
        settings.api_hash,
        device_model=settings.device_model,
        system_version=settings.system_version,
        app_version=settings.app_version,
        proxy=parse_proxy(proxy),
        # Короткие FloodWait Telethon пересиживает сам; всё остальное
        # обрабатывает FloodGuard, поэтому порог занижен.
        flood_sleep_threshold=0,
    )


async def client_for_account(
    settings: Settings, account: Account, cipher: SessionCipher
) -> TelegramClient:
    """Подключённый клиент для сохранённого аккаунта."""
    session = cipher.decrypt(account.session_enc)
    client = new_client(settings, session=session, proxy=account.proxy)
    await client.connect()
    return client
