"""Разбор строки прокси в формат, понятный Telethon (python-socks)."""

from __future__ import annotations

from urllib.parse import unquote, urlparse

SUPPORTED_SCHEMES = {"socks5", "socks4", "http", "https"}


class ProxyError(ValueError):
    pass


def parse_proxy(raw: str | None) -> dict | None:
    """``socks5://user:pass@host:1080`` → dict для Telethon.

    Отдельный прокси на аккаунт — не «обход» лимитов, а гигиена: у разных
    аккаунтов не должно быть общего сетевого следа.
    """
    if not raw or not raw.strip():
        return None
    value = raw.strip()
    if "://" not in value:
        value = f"socks5://{value}"

    parsed = urlparse(value)
    scheme = (parsed.scheme or "").lower()
    if scheme not in SUPPORTED_SCHEMES:
        raise ProxyError(
            f"Неподдерживаемая схема прокси: {parsed.scheme}. "
            f"Доступны: {', '.join(sorted(SUPPORTED_SCHEMES))}"
        )
    if not parsed.hostname:
        raise ProxyError("В строке прокси не указан хост")
    if not parsed.port:
        raise ProxyError("В строке прокси не указан порт")

    config: dict = {
        "proxy_type": "http" if scheme == "https" else scheme,
        "addr": parsed.hostname,
        "port": int(parsed.port),
        "rdns": True,
    }
    if parsed.username:
        config["username"] = unquote(parsed.username)
    if parsed.password:
        config["password"] = unquote(parsed.password)
    return config


def redact_proxy(raw: str | None) -> str:
    """Строка прокси без пароля — для показа в интерфейсе и в логах."""
    if not raw:
        return "нет"
    try:
        config = parse_proxy(raw)
    except ProxyError:
        return "некорректный"
    if config is None:
        return "нет"
    auth = f"{config['username']}:***@" if config.get("username") else ""
    return f"{config['proxy_type']}://{auth}{config['addr']}:{config['port']}"
