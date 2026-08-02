"""Сообщения о вступлении в чат.

Telegram сам пишет служебные сообщения, когда человек входит в группу. Они
приезжают вместе с обычной историей и раньше просто выбрасывались — то есть
источник был бесплатным, но неиспользованным. Особенно он важен там, где
список участников скрыт: тогда это единственный способ увидеть тех, кто
вступил и молчит.

Берём только три действия, которые формирует сам Telegram. Логи вступлений,
которые ведут сторонние боты обычным текстом, сюда не относятся.
"""

from __future__ import annotations

from typing import Any

from telethon.tl.types import (
    MessageActionChatAddUser,
    MessageActionChatJoinedByLink,
    MessageActionChatJoinedByRequest,
    PeerUser,
)

# Действия, означающие появление человека в чате.
JOIN_ACTIONS = (
    MessageActionChatAddUser,  # добавили
    MessageActionChatJoinedByLink,  # пришёл по ссылке
    MessageActionChatJoinedByRequest,  # приняли заявку
)


def is_join(message: Any) -> bool:
    return isinstance(getattr(message, "action", None), JOIN_ACTIONS)


def joiner_ids(message: Any) -> list[int]:
    """id людей, появившихся в чате по этому служебному сообщению.

    У «добавили» вступившие перечислены в самом действии, у ссылки и заявки
    вступивший — автор сообщения.
    """
    action = getattr(message, "action", None)
    if action is None:
        return []

    if isinstance(action, MessageActionChatAddUser):
        return [int(uid) for uid in (getattr(action, "users", None) or [])]

    if isinstance(action, (MessageActionChatJoinedByLink, MessageActionChatJoinedByRequest)):
        from_id = getattr(message, "from_id", None)
        if isinstance(from_id, PeerUser):
            return [from_id.user_id]

    return []
