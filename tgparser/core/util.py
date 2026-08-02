"""Чистые функции обхода: ссылки, фильтры, отсечки. Тестируются без сети."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

CHANNEL_ID_PREFIX = -1_000_000_000_000


def strip_channel_prefix(chat_id: int) -> int:
    """Из «помеченного» id канала (-100...) получить внутренний.

    Telethon отдаёт id каналов и в помеченном виде (-1001234567890), и в сыром
    (1234567890) — в зависимости от того, откуда взят объект.
    """
    if chat_id < 0:
        raw = abs(chat_id)
        text = str(raw)
        if text.startswith("100") and len(text) > 3:
            return int(text[3:])
        return raw
    return chat_id


def message_link(
    message_id: int,
    chat_id: int | None = None,
    chat_username: str | None = None,
    topic_id: int | None = None,
) -> str | None:
    """Постоянная ссылка на сообщение.

    Для публичных чатов — по username, для приватных — через /c/<internal_id>.
    Приватная ссылка открывается только у того, кто состоит в чате, но нам
    этого достаточно: открывает её владелец аккаунта.
    """
    if message_id is None or message_id <= 0:
        return None
    if chat_username:
        base = f"https://t.me/{chat_username.lstrip('@')}"
    elif chat_id is not None:
        base = f"https://t.me/c/{strip_channel_prefix(chat_id)}"
    else:
        return None
    if topic_id:
        return f"{base}/{topic_id}/{message_id}"
    return f"{base}/{message_id}"


def cutoff_datetime(depth_days: int, now: datetime | None = None) -> datetime | None:
    """Граница обхода по времени. 0 или меньше — без ограничения."""
    if depth_days <= 0:
        return None
    return (now or datetime.now(UTC)) - timedelta(days=depth_days)


def is_topic_excluded(title: str | None, patterns: list[str]) -> bool:
    """Совпадение названия топика с любым из исключающих шаблонов."""
    if not title or not patterns:
        return False
    lowered = title.casefold()
    return any(p.strip().casefold() in lowered for p in patterns if p.strip())


def chat_matches(chat_id: int, username: str | None, entries: list[str]) -> bool:
    """Есть ли чат в списке (по числовому id или по @username)."""
    if not entries:
        return False
    normalized_username = (username or "").lstrip("@").casefold()
    raw_id = strip_channel_prefix(chat_id)
    for entry in entries:
        item = entry.strip()
        if not item:
            continue
        if item.startswith("@") or not _looks_numeric(item):
            if normalized_username and item.lstrip("@").casefold() == normalized_username:
                return True
        else:
            try:
                if strip_channel_prefix(int(item)) == raw_id:
                    return True
            except ValueError:
                continue
    return False


def _looks_numeric(value: str) -> bool:
    return bool(re.fullmatch(r"-?\d+", value.strip()))


# 4-32 символа: самостоятельно регистрируются теги от пяти, но короткие
# коллекционные с Fragment встречаются, и при ручном вводе ложный отказ
# дороже лишней записи.
USERNAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{3,31}$")


def normalize_username(raw: str) -> str | None:
    """Привести введённый вручную тег к каноничному виду или отвергнуть."""
    if not raw:
        return None
    value = raw.strip()
    for prefix in ("https://t.me/", "http://t.me/", "t.me/", "@"):
        if value.lower().startswith(prefix.lower()):
            value = value[len(prefix) :]
            break
    value = value.split("?", 1)[0].strip("/ ").strip()
    if not value:
        return None
    return value if USERNAME_RE.match(value) else None


def extract_usernames(text: str) -> list[str]:
    """Все валидные теги из произвольного текста, без повторов и с сохранением порядка."""
    found: list[str] = []
    seen: set[str] = set()
    for token in re.split(r"[\s,;]+", text or ""):
        normalized = normalize_username(token)
        if normalized and normalized.casefold() not in seen:
            seen.add(normalized.casefold())
            found.append(normalized)
    return found


def parse_chat_list(text: str) -> list[str]:
    """Разобрать список чатов: @теги, ссылки и числовые id в одном сообщении."""
    found: list[str] = []
    seen: set[str] = set()
    for token in re.split(r"[\s,;]+", text or ""):
        item = token.strip()
        if not item:
            continue
        if _looks_numeric(item):
            normalized = item
        else:
            username = normalize_username(item)
            if username is None:
                continue
            normalized = f"@{username}"
        key = normalized.casefold()
        if key not in seen:
            seen.add(key)
            found.append(normalized)
    return found


def snippet(text: str | None, limit: int = 300) -> str | None:
    """Укороченный текст сообщения для карточки лида."""
    if not text:
        return None
    collapsed = " ".join(text.split())
    if not collapsed:
        return None
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 1].rstrip() + "…"


def humanize_seconds(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds} с"
    if seconds < 3600:
        return f"{seconds // 60} мин {seconds % 60} с"
    hours, rest = divmod(seconds, 3600)
    return f"{hours} ч {rest // 60} мин"
