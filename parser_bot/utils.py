"""Утилиты: нормализация ссылок на чаты/каналы и извлечение ссылок из текста."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

# t.me/username, @username, https://t.me/username, t.me/+hash, t.me/joinchat/hash
_TME_RE = re.compile(
    r"(?:https?://)?(?:t(?:elegram)?\.me|telegram\.dog)/"
    r"(?P<rest>[a-zA-Z0-9_+/\-]+)",
    re.IGNORECASE,
)
_USERNAME_RE = re.compile(r"@([a-zA-Z][a-zA-Z0-9_]{3,})")


@dataclass(frozen=True)
class ChatRef:
    ident: str  # нормализованный уникальный ключ
    link: str   # ссылка для входа (t.me/...)
    kind: str   # 'username' | 'invite'


def _from_username(username: str) -> ChatRef:
    username = username.lstrip("@").lower()
    return ChatRef(ident=f"@{username}", link=f"https://t.me/{username}", kind="username")


def _from_invite(hash_: str) -> ChatRef:
    hash_ = hash_.strip("+/")
    return ChatRef(ident=f"invite:{hash_}", link=f"https://t.me/+{hash_}", kind="invite")


def normalize(raw: str) -> Optional[ChatRef]:
    """Превращает произвольную ссылку/упоминание в ChatRef. None если не похоже на чат."""
    if not raw:
        return None
    raw = raw.strip()

    m = _TME_RE.search(raw)
    if m:
        rest = m.group("rest")
        # приватные приглашения
        if rest.startswith("+"):
            return _from_invite(rest[1:])
        if rest.lower().startswith("joinchat/"):
            return _from_invite(rest.split("/", 1)[1])
        # публичный юзернейм (берём первый сегмент, отбрасываем /123 message-id)
        first = rest.split("/", 1)[0]
        if first.startswith("+"):
            return _from_invite(first[1:])
        # отбрасываем служебные сегменты
        if first.lower() in {"s", "share", "addstickers", "joinchat", "proxy", "socks"}:
            return None
        if re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_]{3,}", first):
            return _from_username(first)
        return None

    if raw.startswith("@"):
        m2 = _USERNAME_RE.match(raw)
        if m2:
            return _from_username(m2.group(1))

    # голый username без @ и без ссылки
    if re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_]{3,}", raw):
        return _from_username(raw)

    return None


def extract_refs(text: str, *, extra: Optional[list[str]] = None) -> list[ChatRef]:
    """Достаёт все ссылки на чаты из текста (+ дополнительные строки, напр. url кнопок)."""
    found: dict[str, ChatRef] = {}
    sources: list[str] = []
    if text:
        sources.append(text)
        for m in _TME_RE.finditer(text):
            sources.append(m.group(0))
        for m in _USERNAME_RE.finditer(text):
            sources.append(m.group(0))
    if extra:
        sources.extend(extra)

    for s in sources:
        ref = normalize(s)
        if ref and ref.ident not in found:
            found[ref.ident] = ref
    return list(found.values())
