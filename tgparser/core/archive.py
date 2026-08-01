"""Архивный канал: карточки пользователей без тега и сводки по прогонам.

Пользователя без ``username`` нельзя записать тегом, поэтому его сообщение
пересылается в отдельный канал — карточка в канале даёт переход в профиль.
У этого механизма есть штатная деградация: если у автора включено
«Пересланные сообщения → Никто», сервер отдаёт ``fwd_from`` без ``from_id``,
и ссылки на профиль в карточке не будет. Такие записи помечаются флагом,
и для них дополнительно сохраняется прямая ссылка на исходное сообщение.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from telethon.errors import (
    ChatForwardsRestrictedError,
    ChatWriteForbiddenError,
    RPCError,
)
from telethon.tl.functions.channels import CreateChannelRequest

from tgparser.core.util import message_link
from tgparser.ratelimit.guard import FloodGuard

logger = logging.getLogger(__name__)

ARCHIVE_TITLE = "Парсер · архив"
ARCHIVE_ABOUT = (
    "Карточки пользователей без @тега: пересланные сообщения ведут в профиль. "
    "Канал создан автоматически."
)


@dataclass(slots=True)
class ForwardResult:
    link: str | None
    anonymized: bool
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.link is not None


class Archive:
    def __init__(self, client: Any, guard: FloodGuard, channel_id: int | None = None) -> None:
        self._client = client
        self._guard = guard
        self._channel_id = channel_id
        self._entity: Any | None = None

    @property
    def channel_id(self) -> int | None:
        return self._channel_id

    async def ensure(self) -> Any:
        """Вернуть канал, создав его при первом обращении. Создаётся однократно."""
        if self._entity is not None:
            return self._entity

        if self._channel_id is not None:
            try:
                self._entity = await self._client.get_entity(self._channel_id)
                return self._entity
            except (RPCError, ValueError) as exc:
                logger.warning(
                    "Архивный канал %s недоступен (%s), создаю новый", self._channel_id, exc
                )
                self._channel_id = None

        result = await self._guard.call(
            "write",
            self._client,
            CreateChannelRequest(
                title=ARCHIVE_TITLE,
                about=ARCHIVE_ABOUT,
                broadcast=True,
                megagroup=False,
            ),
        )
        channels = getattr(result, "chats", None) or []
        if not channels:
            raise RuntimeError("Telegram не вернул созданный канал")
        self._entity = channels[0]
        from telethon.utils import get_peer_id

        self._channel_id = get_peer_id(self._entity)
        logger.info("Создан архивный канал %s", self._channel_id)
        return self._entity

    async def forward(self, message: Any, from_peer: Any) -> ForwardResult:
        """Переслать сообщение в архив и понять, сохранилась ли ссылка на автора."""
        try:
            entity = await self.ensure()
        except (RPCError, RuntimeError) as exc:
            return ForwardResult(link=None, anonymized=False, error=str(exc))

        try:
            sent = await self._guard.call(
                "write",
                self._client.forward_messages,
                entity,
                message.id,
                from_peer,
            )
        except ChatForwardsRestrictedError:
            # В чате включена защита контента — пересылка запрещена целиком.
            return ForwardResult(
                link=None, anonymized=False, error="в чате запрещена пересылка"
            )
        except ChatWriteForbiddenError as exc:
            return ForwardResult(link=None, anonymized=False, error=str(exc))
        except RPCError as exc:
            logger.warning("Пересылка не удалась: %s", exc)
            return ForwardResult(link=None, anonymized=False, error=str(exc))

        forwarded = sent[0] if isinstance(sent, list) else sent
        if forwarded is None:
            return ForwardResult(link=None, anonymized=False, error="Telegram не вернул сообщение")

        fwd = getattr(forwarded, "fwd_from", None)
        anonymized = fwd is not None and getattr(fwd, "from_id", None) is None
        link = message_link(forwarded.id, chat_id=self._channel_id)
        return ForwardResult(link=link, anonymized=anonymized)

    async def post(self, text: str) -> None:
        """Сводка в канал. Ошибки не критичны — прогон из-за них не рушим."""
        try:
            entity = await self.ensure()
            await self._guard.call("write", self._client.send_message, entity, text)
        except (RPCError, RuntimeError) as exc:
            logger.warning("Не удалось написать в архивный канал: %s", exc)
