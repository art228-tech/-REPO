"""Заглушка Telethon-клиента для тестов сканера.

Повторяет то поведение настоящего API, на которое опирается код: ответ
``messages.getHistory`` приносит и сообщения, и объекты их авторов, поэтому
сканер не должен запрашивать профили отдельно. Заглушка считает все вызовы,
и тесты на этом проверяют, что лишних запросов нет.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from telethon.tl.functions.channels import CreateChannelRequest, GetParticipantsRequest
from telethon.tl.functions.messages import (
    GetForumTopicsRequest,
    GetFullChatRequest,
    GetHistoryRequest,
)
from telethon.tl.types import ForumTopic, PeerUser
from telethon.utils import get_peer_id

from tests.factories import make_channel, make_forwarded


@dataclass
class ChatFixture:
    entity: Any
    messages: list[Any] = field(default_factory=list)  # от новых к старым
    participants: list[Any] = field(default_factory=list)
    participants_hidden: bool = False
    can_view_participants: bool = True
    participants_count: int = 100
    linked_chat_id: int | None = None
    topics: list[tuple[int, str, int]] = field(default_factory=list)
    forward_error: Exception | None = None
    forward_anonymized: bool = False

    @property
    def peer_id(self) -> int:
        return get_peer_id(self.entity)


class _Dialog:
    def __init__(self, entity: Any) -> None:
        self.entity = entity
        self.is_user = False


class _FullChat:
    def __init__(self, fixture: ChatFixture) -> None:
        self.participants_hidden = fixture.participants_hidden
        self.can_view_participants = fixture.can_view_participants
        self.participants_count = fixture.participants_count
        self.linked_chat_id = fixture.linked_chat_id
        self.participants = None


class _Result:
    def __init__(self, **kwargs: Any) -> None:
        self.__dict__.update(kwargs)


class FakeTelegramClient:
    def __init__(self, fixtures: list[ChatFixture], users: dict[int, Any]) -> None:
        self._fixtures = {f.peer_id: f for f in fixtures}
        self._by_raw_id = {f.entity.id: f for f in fixtures}
        self._users = users
        self.calls: list[str] = []
        self.forwarded: list[tuple[int, int]] = []
        self.created_channels = 0
        self.sent_messages: list[str] = []
        self._archive = make_channel(555000111, title="Архив", megagroup=False, broadcast=True)

    # --- учёт вызовов ---

    def count(self, name: str) -> int:
        return sum(1 for call in self.calls if call == name)

    # --- поверхность Telethon ---

    async def iter_dialogs(self):
        self.calls.append("iter_dialogs")
        for fixture in self._fixtures.values():
            yield _Dialog(fixture.entity)

    async def get_entity(self, ident: Any):
        self.calls.append("get_entity")
        if isinstance(ident, int):
            fixture = self._fixtures.get(ident) or self._by_raw_id.get(abs(ident))
            if fixture is not None:
                return fixture.entity
            if ident == get_peer_id(self._archive):
                return self._archive
            raise ValueError(f"нет такой сущности: {ident}")
        return ident

    async def forward_messages(self, entity: Any, message_id: int, from_peer: Any):
        self.calls.append("forward_messages")
        fixture = self._fixtures.get(get_peer_id(from_peer))
        if fixture is not None and fixture.forward_error is not None:
            raise fixture.forward_error
        self.forwarded.append((get_peer_id(from_peer), message_id))
        anonymized = fixture.forward_anonymized if fixture else False
        return make_forwarded(9000 + len(self.forwarded), anonymized=anonymized)

    async def send_message(self, entity: Any, text: str):
        self.calls.append("send_message")
        self.sent_messages.append(text)

    async def __call__(self, request: Any):
        if isinstance(request, GetHistoryRequest):
            return self._history(request)
        if isinstance(request, GetParticipantsRequest):
            return self._participants(request)
        if isinstance(request, GetForumTopicsRequest):
            return self._forum_topics(request)
        if isinstance(request, GetFullChatRequest):
            return self._full_basic(request)
        if isinstance(request, CreateChannelRequest):
            return self._create_channel()
        # GetFullChannelRequest импортируется отдельно, чтобы не путать с чатом.
        from telethon.tl.functions.channels import GetFullChannelRequest

        if isinstance(request, GetFullChannelRequest):
            return self._full_channel(request)
        raise AssertionError(f"неожиданный запрос: {type(request).__name__}")

    # --- реализации ---

    def _fixture_for(self, peer: Any) -> ChatFixture:
        if isinstance(peer, int):
            return self._fixtures[peer]
        return self._fixtures[get_peer_id(peer)]

    def _history(self, request: GetHistoryRequest) -> _Result:
        self.calls.append("GetHistory")
        fixture = self._fixture_for(request.peer)
        messages = fixture.messages
        if request.offset_id:
            messages = [m for m in messages if m.id < request.offset_id]
        page = messages[: request.limit]

        sender_ids = {
            m.from_id.user_id for m in page if isinstance(getattr(m, "from_id", None), PeerUser)
        }
        users = [self._users[uid] for uid in sender_ids if uid in self._users]
        return _Result(messages=page, users=users, chats=[])

    def _participants(self, request: GetParticipantsRequest) -> _Result:
        self.calls.append("GetParticipants")
        fixture = self._fixture_for(request.channel)
        page = fixture.participants[request.offset : request.offset + request.limit]
        return _Result(users=page, count=len(fixture.participants))

    def _forum_topics(self, request: GetForumTopicsRequest) -> _Result:
        self.calls.append("GetForumTopics")
        fixture = self._fixture_for(request.peer)
        topics = []
        for topic_id, title, top_message in fixture.topics:
            topic = ForumTopic.__new__(ForumTopic)
            topic.__dict__.update(
                id=topic_id, title=title, top_message=top_message, date=None
            )
            topics.append(topic)
        return _Result(topics=topics)

    def _full_channel(self, request: Any) -> _Result:
        self.calls.append("GetFullChannel")
        fixture = self._fixture_for(request.channel)
        return _Result(full_chat=_FullChat(fixture), users=[], chats=[])

    def _full_basic(self, request: GetFullChatRequest) -> _Result:
        self.calls.append("GetFullChat")
        fixture = self._by_raw_id[request.chat_id]
        full = _FullChat(fixture)
        full.participants = _Result(participants=fixture.participants)
        return _Result(full_chat=full, users=list(fixture.participants), chats=[])

    def _create_channel(self) -> _Result:
        self.calls.append("CreateChannel")
        self.created_channels += 1
        return _Result(chats=[self._archive])
