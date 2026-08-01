"""Отбор пользователей. Работает по утиной типизации — тестируется без Telethon."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class UserLike(Protocol):
    id: int
    bot: bool
    deleted: bool
    username: str | None


@dataclass(frozen=True, slots=True)
class SkipReason:
    code: str
    text: str


SKIP_BOT = SkipReason("bot", "бот")
SKIP_DELETED = SkipReason("deleted", "удалённый аккаунт")
SKIP_SELF = SkipReason("self", "собственный аккаунт")
SKIP_NOT_USER = SkipReason("not_user", "не пользователь (канал/аноним)")
SKIP_SEEN = SkipReason("seen", "уже в базе")


def active_username(user: Any) -> str | None:
    """Активный username.

    У аккаунта может быть несколько тегов (коллекционные): в объекте они лежат
    в ``usernames``, а в ``username`` — только основной. Берём активный.
    """
    usernames = getattr(user, "usernames", None)
    if usernames:
        for item in usernames:
            if getattr(item, "active", False):
                value = getattr(item, "username", None)
                if value:
                    return value
    value = getattr(user, "username", None)
    return value or None


def classify_user(
    user: Any,
    *,
    skip_bots: bool = True,
    skip_deleted: bool = True,
    self_id: int | None = None,
    seen: set[int] | None = None,
) -> SkipReason | None:
    """``None`` — пользователя берём, иначе причина пропуска."""
    if user is None or getattr(user, "id", None) is None:
        return SKIP_NOT_USER
    # Анонимные админы и посты от имени канала приходят как Channel, не User.
    if not _is_user(user):
        return SKIP_NOT_USER
    if self_id is not None and user.id == self_id:
        return SKIP_SELF
    if skip_bots and getattr(user, "bot", False):
        return SKIP_BOT
    if skip_deleted and getattr(user, "deleted", False):
        return SKIP_DELETED
    if seen is not None and user.id in seen:
        return SKIP_SEEN
    return None


def _is_user(entity: Any) -> bool:
    """Отличить User от Channel/Chat без импорта Telethon."""
    if hasattr(entity, "bot") or hasattr(entity, "first_name"):
        return True
    # У Channel есть broadcast/megagroup, у User их нет.
    return not (hasattr(entity, "broadcast") or hasattr(entity, "megagroup"))
