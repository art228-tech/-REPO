"""Фабрики объектов Telethon для тестов.

Настоящие типы конструируются через ``__new__``: у них длинные обязательные
подписи, а для тестов важны только те поля, которые читает код.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from telethon.tl.types import (
    Channel,
    Chat,
    Message,
    MessageActionChatAddUser,
    MessageActionChatDeleteUser,
    MessageActionChatJoinedByLink,
    MessageActionChatJoinedByRequest,
    MessageService,
    PeerChannel,
    PeerUser,
    User,
    Username,
)


def make_user(
    user_id: int,
    username: str | None = None,
    first_name: str = "Имя",
    last_name: str | None = None,
    bot: bool = False,
    deleted: bool = False,
    premium: bool = False,
    usernames: list[tuple[str, bool]] | None = None,
) -> User:
    user = User.__new__(User)
    user.__dict__.update(
        id=user_id,
        username=username,
        first_name=first_name,
        last_name=last_name,
        bot=bot,
        deleted=deleted,
        premium=premium,
        phone=None,
        access_hash=user_id * 7,
        min=False,
        usernames=[_username(name, active) for name, active in (usernames or [])] or None,
    )
    return user


def _username(name: str, active: bool) -> Username:
    item = Username.__new__(Username)
    item.__dict__.update(username=name, editable=False, active=active)
    return item


def make_channel(
    channel_id: int,
    title: str = "Чат",
    username: str | None = None,
    megagroup: bool = True,
    broadcast: bool = False,
    forum: bool = False,
) -> Channel:
    channel = Channel.__new__(Channel)
    channel.__dict__.update(
        id=channel_id,
        title=title,
        username=username,
        megagroup=megagroup,
        broadcast=broadcast,
        forum=forum,
        access_hash=channel_id * 3,
        min=False,
    )
    return channel


def make_basic_group(chat_id: int, title: str = "Группа") -> Chat:
    chat = Chat.__new__(Chat)
    chat.__dict__.update(
        id=chat_id,
        title=title,
        migrated_to=None,
        deactivated=False,
        participants_count=12,
    )
    return chat


def make_message(
    message_id: int,
    from_user_id: int | None,
    text: str = "текст",
    days_ago: float = 0,
    topic_id: int | None = None,
    from_channel_id: int | None = None,
) -> Message:
    message = Message.__new__(Message)
    from_id: Any = None
    if from_user_id is not None:
        from_id = PeerUser(user_id=from_user_id)
    elif from_channel_id is not None:
        from_id = PeerChannel(channel_id=from_channel_id)

    message.__dict__.update(
        id=message_id,
        from_id=from_id,
        message=text,
        date=datetime.now(UTC) - timedelta(days=days_ago),
        reply_to=_reply_to(topic_id) if topic_id else None,
        fwd_from=None,
    )
    return message


def make_service_message(
    message_id: int,
    from_user_id: int,
    days_ago: float = 0,
    action: Any = None,
) -> MessageService:
    message = MessageService.__new__(MessageService)
    message.__dict__.update(
        id=message_id,
        from_id=PeerUser(user_id=from_user_id),
        date=datetime.now(UTC) - timedelta(days=days_ago),
        reply_to=None,
        action=action,
    )
    return message


def make_added(message_id: int, adder_id: int, added_ids: list[int], days_ago: float = 0):
    """«X добавил Y» — вступившие перечислены в самом действии."""
    return make_service_message(
        message_id, adder_id, days_ago, MessageActionChatAddUser(users=added_ids)
    )


def make_joined_by_link(message_id: int, user_id: int, days_ago: float = 0):
    """«X присоединился по ссылке» — вступивший это автор сообщения."""
    return make_service_message(
        message_id, user_id, days_ago, MessageActionChatJoinedByLink(inviter_id=1)
    )


def make_joined_by_request(message_id: int, user_id: int, days_ago: float = 0):
    """«Заявка X принята» — вступивший это автор сообщения."""
    return make_service_message(
        message_id, user_id, days_ago, MessageActionChatJoinedByRequest()
    )


def make_left(message_id: int, user_id: int, days_ago: float = 0):
    """Выход из чата — не вступление, учитываться не должен."""
    return make_service_message(
        message_id, user_id, days_ago, MessageActionChatDeleteUser(user_id=user_id)
    )


def _reply_to(topic_id: int) -> Any:
    class _ReplyTo:
        def __init__(self, top_id: int) -> None:
            self.reply_to_top_id = top_id
            self.reply_to_msg_id = top_id
            self.forum_topic = True

    return _ReplyTo(topic_id)


def make_forwarded(message_id: int, anonymized: bool) -> Message:
    """Сообщение, каким оно вернулось после пересылки в архив."""
    message = Message.__new__(Message)

    class _Fwd:
        def __init__(self, hidden: bool) -> None:
            self.from_id = None if hidden else PeerUser(user_id=1)
            self.from_name = "Кто-то" if hidden else None

    message.__dict__.update(id=message_id, fwd_from=_Fwd(anonymized), message="переслано")
    return message
