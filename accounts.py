from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from telethon import TelegramClient
from telethon.errors import (
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    SessionPasswordNeededError,
)

import config
from db import ProxyConfig, db
from logger_setup import log

# Keep clients during auth flow
_auth_clients: dict[int, TelegramClient] = {}
_runtime_clients: dict[int, TelegramClient] = {}


def session_path(session_name: str) -> str:
    return str(config.SESSIONS_DIR / session_name)


def normalize_phone(phone: str) -> str:
    phone = phone.strip().replace(" ", "").replace("-", "")
    if not phone.startswith("+") and phone.isdigit():
        phone = "+" + phone
    return phone


async def build_client(
    session_name: str,
    api_id: int,
    api_hash: str,
    proxy_json: str | None = None,
) -> TelegramClient:
    proxy = None
    if proxy_json:
        proxy = ProxyConfig.parse(
            # allow either raw url string stored or json
            _proxy_raw_from_json(proxy_json)
        ).to_telethon()
    client = TelegramClient(
        session_path(session_name),
        api_id,
        api_hash,
        proxy=proxy,
        connection_retries=3,
        retry_delay=2,
        auto_reconnect=True,
        request_retries=3,
    )
    return client


def _proxy_raw_from_json(proxy_json: str) -> str:
    import json

    try:
        data = json.loads(proxy_json)
        if isinstance(data, str):
            return data
        ptype = data.get("proxy_type", "socks5")
        host = data["host"]
        port = data["port"]
        user = data.get("username")
        password = data.get("password")
        if user:
            return f"{ptype}://{user}:{password or ''}@{host}:{port}"
        return f"{ptype}://{host}:{port}"
    except Exception:
        return proxy_json


async def start_login(
    user_id: int,
    phone: str,
    proxy_raw: str | None = None,
) -> str:
    api_id, api_hash = await db.get_api_credentials()
    if not api_id or not api_hash:
        raise RuntimeError(
            "Сначала укажи API_ID и API_HASH в настройках "
            "(my.telegram.org → API development tools)."
        )

    phone = normalize_phone(phone)
    proxy_json = None
    if proxy_raw:
        proxy = ProxyConfig.parse(proxy_raw)
        proxy_json = proxy.to_json()

    session_name = f"acc_{phone.replace('+', '')}"
    # disconnect previous auth client if any
    old = _auth_clients.pop(user_id, None)
    if old:
        try:
            await old.disconnect()
        except Exception:
            pass

    client = await build_client(session_name, api_id, api_hash, proxy_json)
    await client.connect()
    result = await client.send_code_request(phone)
    _auth_clients[user_id] = client
    await db.set_pending_auth(
        user_id,
        phone=phone,
        phone_code_hash=result.phone_code_hash,
        proxy_json=proxy_json,
        step="code",
    )
    log.info("Login code requested for %s (user %s)", phone, user_id)
    return phone


async def complete_login_code(user_id: int, code: str) -> dict[str, Any]:
    pending = await db.get_pending_auth(user_id)
    if not pending or not pending["phone"]:
        raise RuntimeError("Нет активного входа. Начни добавление аккаунта заново.")

    client = _auth_clients.get(user_id)
    if not client:
        raise RuntimeError("Сессия входа потеряна. Начни заново.")

    phone = pending["phone"]
    phone_code_hash = pending["phone_code_hash"]
    code = code.strip().replace(" ", "")

    try:
        await client.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash)
    except SessionPasswordNeededError:
        await db.set_pending_auth(user_id, step="2fa")
        return {"need_2fa": True}
    except PhoneCodeInvalidError as e:
        raise RuntimeError("Неверный код.") from e
    except PhoneCodeExpiredError as e:
        raise RuntimeError("Код истёк. Начни вход заново.") from e

    return await _finalize_login(user_id, client, phone, pending["proxy_json"])


async def complete_login_2fa(user_id: int, password: str) -> dict[str, Any]:
    pending = await db.get_pending_auth(user_id)
    if not pending:
        raise RuntimeError("Нет активного входа.")
    client = _auth_clients.get(user_id)
    if not client:
        raise RuntimeError("Сессия входа потеряна.")
    await client.sign_in(password=password.strip())
    return await _finalize_login(
        user_id, client, pending["phone"], pending["proxy_json"]
    )


async def _finalize_login(
    user_id: int,
    client: TelegramClient,
    phone: str,
    proxy_json: str | None,
) -> dict[str, Any]:
    me = await client.get_me()
    session_name = f"acc_{phone.replace('+', '')}"
    account_id = await db.add_account(
        phone=phone,
        session_name=session_name,
        proxy_json=proxy_json,
        status="active",
    )
    await client.disconnect()
    _auth_clients.pop(user_id, None)
    await db.clear_pending_auth(user_id)
    log.info("Account authorized: %s id=%s tg_id=%s", phone, account_id, me.id)
    return {
        "need_2fa": False,
        "account_id": account_id,
        "phone": phone,
        "tg_id": me.id,
        "username": me.username,
        "name": f"{me.first_name or ''} {me.last_name or ''}".strip(),
    }


async def cancel_login(user_id: int) -> None:
    client = _auth_clients.pop(user_id, None)
    if client:
        try:
            await client.disconnect()
        except Exception:
            pass
    await db.clear_pending_auth(user_id)


async def get_runtime_client(account_id: int) -> TelegramClient:
    if account_id in _runtime_clients:
        client = _runtime_clients[account_id]
        if client.is_connected():
            return client
        try:
            await client.connect()
            return client
        except Exception:
            _runtime_clients.pop(account_id, None)

    account = await db.get_account(account_id)
    if not account:
        raise RuntimeError(f"Account {account_id} not found")
    api_id, api_hash = await db.get_api_credentials()
    client = await build_client(
        account["session_name"], api_id, api_hash, account["proxy_json"]
    )
    await client.connect()
    if not await client.is_user_authorized():
        await db.update_account(
            account_id, status="error", last_error="Session unauthorized"
        )
        raise RuntimeError(f"Account {account['phone']} session is not authorized")
    _runtime_clients[account_id] = client
    return client


async def disconnect_account(account_id: int) -> None:
    client = _runtime_clients.pop(account_id, None)
    if client:
        try:
            await client.disconnect()
        except Exception:
            pass


async def disconnect_all() -> None:
    for account_id in list(_runtime_clients.keys()):
        await disconnect_account(account_id)
    for user_id in list(_auth_clients.keys()):
        await cancel_login(user_id)


async def check_account_alive(account_id: int) -> tuple[bool, str]:
    try:
        client = await get_runtime_client(account_id)
        me = await client.get_me()
        return True, f"ok @{me.username}" if me.username else f"ok id={me.id}"
    except Exception as e:
        log.exception("Account check failed id=%s", account_id)
        return False, str(e)


async def set_account_proxy(account_id: int, proxy_raw: str | None) -> None:
    proxy_json = None
    if proxy_raw and proxy_raw.strip().lower() not in ("none", "-", "удалить", "delete"):
        proxy_json = ProxyConfig.parse(proxy_raw.strip()).to_json()
    await db.update_account(account_id, proxy_json=proxy_json if proxy_json is not None else "")
    await disconnect_account(account_id)
    # reconnect with new proxy if was runtime
    log.info("Proxy updated for account %s", account_id)


async def remove_account(account_id: int) -> None:
    account = await db.get_account(account_id)
    await disconnect_account(account_id)
    await db.delete_account(account_id)
    if account:
        path = Path(session_path(account["session_name"]) + ".session")
        for p in (path, Path(str(path) + "-journal")):
            try:
                if p.exists():
                    p.unlink()
            except Exception:
                pass


async def clear_spamblock_flag(account_id: int) -> None:
    await db.update_account(account_id, clear_spamblock=True, status="active", last_error="")
    log.info("Spamblock flag cleared for account %s", account_id)


async def mark_spamblock(account_id: int, error: str) -> None:
    await db.update_account(
        account_id,
        status="spamblock",
        last_error=error,
        set_spamblock=True,
    )
    log.warning("Account %s marked spamblock: %s", account_id, error)