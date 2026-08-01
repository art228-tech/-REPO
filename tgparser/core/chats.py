"""Разбор диалогов: тип чата, видимость участников, привязанные обсуждения."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from telethon.errors import ChannelPrivateError, RPCError
from telethon.tl.functions.channels import GetFullChannelRequest
from telethon.tl.functions.messages import GetForumTopicsRequest, GetFullChatRequest
from telethon.tl.types import Channel, Chat, ForumTopic

from tgparser.db.models import ChatKind
from tgparser.ratelimit.guard import FloodGuard

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class TopicInfo:
    id: int
    title: str
    top_message: int


@dataclass(slots=True)
class ChatTarget:
    """Всё, что нужно знать о чате перед обходом."""

    entity: Any
    chat_id: int
    title: str
    username: str | None
    kind: ChatKind
    participants_count: int | None = None
    # None означает «не удалось определить».
    participants_visible: bool | None = None
    linked_chat_id: int | None = None
    topics: list[TopicInfo] | None = None
    # У обычных групп участники приезжают вместе с метаданными, повторный
    # запрос не нужен.
    preloaded_users: list[Any] = field(default_factory=list)

    @property
    def is_channel(self) -> bool:
        return self.kind is ChatKind.CHANNEL

    @property
    def is_forum(self) -> bool:
        return self.kind is ChatKind.FORUM

    @property
    def busiest_topic(self) -> TopicInfo | None:
        """Топик с самой свежей активностью.

        Точного числа сообщений в топике MTProto не отдаёт, поэтому берём
        наибольший ``top_message`` — это приближение, а не точный подсчёт.
        """
        if not self.topics:
            return None
        return max(self.topics, key=lambda t: t.top_message)


def classify(entity: Any) -> ChatKind | None:
    """Тип чата. ``None`` — не групповой чат и не канал (личка, бот и т.п.)."""
    if isinstance(entity, Chat):
        return ChatKind.GROUP
    if isinstance(entity, Channel):
        if getattr(entity, "broadcast", False):
            return ChatKind.CHANNEL
        if getattr(entity, "forum", False):
            return ChatKind.FORUM
        return ChatKind.SUPERGROUP
    return None


async def inspect(
    client: Any, guard: FloodGuard, entity: Any, marked_id: int
) -> ChatTarget | None:
    """Собрать метаданные чата.

    Видимость участников определяется по флагам ``participants_hidden`` и
    ``can_view_participants`` из ``channelFull``, а не по тексту описания:
    описание к этой настройке отношения не имеет.
    """
    kind = classify(entity)
    if kind is None:
        return None

    target = ChatTarget(
        entity=entity,
        chat_id=marked_id,
        title=getattr(entity, "title", None) or str(marked_id),
        username=getattr(entity, "username", None),
        kind=kind,
    )

    try:
        if isinstance(entity, Chat):
            full = await guard.call("meta", client, GetFullChatRequest(chat_id=entity.id))
            full_chat = full.full_chat
            # В обычных группах список участников отдаётся всегда.
            target.participants_visible = True
            participants = getattr(full_chat, "participants", None)
            members = getattr(participants, "participants", None)
            target.participants_count = len(members) if members is not None else None
            target.preloaded_users = list(getattr(full, "users", None) or [])
        else:
            full = await guard.call("meta", client, GetFullChannelRequest(channel=entity))
            full_chat = full.full_chat
            hidden = bool(getattr(full_chat, "participants_hidden", False))
            can_view = bool(getattr(full_chat, "can_view_participants", False))
            target.participants_visible = can_view and not hidden
            target.participants_count = getattr(full_chat, "participants_count", None)
            target.linked_chat_id = getattr(full_chat, "linked_chat_id", None)
    except ChannelPrivateError:
        logger.info("Нет доступа к %s (%s)", target.title, marked_id)
        return None
    except RPCError as exc:
        logger.warning("Не удалось получить метаданные %s: %s", target.title, exc)
        target.participants_visible = None

    if target.is_forum:
        target.topics = await fetch_topics(client, guard, entity)

    return target


async def fetch_topics(client: Any, guard: FloodGuard, entity: Any) -> list[TopicInfo]:
    """Список топиков форум-группы."""
    topics: list[TopicInfo] = []
    offset_id = 0
    offset_date = None
    offset_topic = 0
    page_size = 100

    while True:
        try:
            result = await guard.call(
                "meta",
                client,
                GetForumTopicsRequest(
                    peer=entity,
                    offset_date=offset_date,
                    offset_id=offset_id,
                    offset_topic=offset_topic,
                    limit=page_size,
                ),
            )
        except RPCError as exc:
            logger.warning("Не удалось получить топики: %s", exc)
            break

        returned = getattr(result, "topics", None) or []
        page = [t for t in returned if isinstance(t, ForumTopic)]
        for topic in page:
            topics.append(
                TopicInfo(
                    id=topic.id,
                    title=topic.title,
                    top_message=getattr(topic, "top_message", 0) or 0,
                )
            )
        if len(returned) < page_size or not page:
            break

        last = page[-1]
        offset_topic = last.id
        offset_id = getattr(last, "top_message", 0) or 0
        offset_date = getattr(last, "date", None)

    return topics


def topic_id_of(message: Any) -> int | None:
    """id топика, к которому относится сообщение форума.

    У сообщений в General топика реквизита нет — возвращаем ``None``.
    """
    reply_to = getattr(message, "reply_to", None)
    if reply_to is None:
        return None
    top_id = getattr(reply_to, "reply_to_top_id", None)
    if top_id:
        return top_id
    if getattr(reply_to, "forum_topic", False):
        return getattr(reply_to, "reply_to_msg_id", None)
    return None
