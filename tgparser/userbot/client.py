"""Создание Telethon-клиентов."""

from __future__ import annotations

import logging

from telethon import TelegramClient
from telethon.sessions import StringSession

from tgparser.config import Settings
from tgparser.crypto import SessionCipher
from tgparser.db.models import Account
from tgparser.userbot.appkeys import AppKeys
from tgparser.userbot.proxy import parse_proxy

logger = logging.getLogger(__name__)


class MissingAppKeysError(RuntimeError):
    pass


def resolve_keys(settings: Settings, keys: AppKeys | None) -> AppKeys:
    """Ключи аккаунта, иначе общие из окружения."""
    if keys is not None:
        return keys
    if settings.api_id and settings.api_hash:
        return AppKeys(api_id=settings.api_id, api_hash=settings.api_hash)
    raise MissingAppKeysError(
        "Нет ключей приложения: ни у аккаунта, ни в настройках бота. "
        "Получите api_id и api_hash при подключении аккаунта."
    )


def new_client(
    settings: Settings,
    keys: AppKeys | None = None,
    session: str | StringSession | None = None,
    proxy: str | None = None,
) -> TelegramClient:
    """Клиент с отпечатком реального приложения.

    Значения device_model / system_version / app_version по умолчанию Telethon
    подставляет свои, и они заметно отличаются от официальных клиентов.
    """
    resolved = resolve_keys(settings, keys)
    return TelegramClient(
        StringSession(session) if not isinstance(session, StringSession) else session,
        resolved.api_id,
        resolved.api_hash,
        device_model=settings.device_model,
        system_version=settings.system_version,
        app_version=settings.app_version,
        proxy=parse_proxy(proxy),
        # Короткие FloodWait Telethon пересиживает сам; всё остальное
        # обрабатывает FloodGuard, поэтому порог занижен.
        flood_sleep_threshold=0,
    )


def keys_of(account: Account, cipher: SessionCipher) -> AppKeys | None:
    if not account.api_id or not account.api_hash_enc:
        return None
    return AppKeys(api_id=account.api_id, api_hash=cipher.decrypt(account.api_hash_enc))


async def client_for_account(
    settings: Settings, account: Account, cipher: SessionCipher
) -> TelegramClient:
    """Подключённый клиент для сохранённого аккаунта."""
    client = new_client(
        settings,
        keys=keys_of(account, cipher),
        session=cipher.decrypt(account.session_enc),
        proxy=account.proxy,
    )
    await client.connect()
    return client
