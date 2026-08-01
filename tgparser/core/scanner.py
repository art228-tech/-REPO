"""Обход чатов и сбор пользователей."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from telethon.errors import ChannelPrivateError, RPCError
from telethon.tl.functions.channels import GetParticipantsRequest
from telethon.tl.functions.messages import GetHistoryRequest
from telethon.tl.types import ChannelParticipantsSearch, MessageService, PeerUser
from telethon.utils import get_peer_id

from tgparser.core.archive import Archive
from tgparser.core.chats import ChatTarget, inspect, topic_id_of
from tgparser.core.filters import active_username, classify_user
from tgparser.core.util import (
    chat_matches,
    cutoff_datetime,
    is_topic_excluded,
    message_link,
    snippet,
)
from tgparser.db.models import ChatKind, ChatState, Lead, SourceKind
from tgparser.db.repo import ChatStateRepo, CollectedUser, LeadRepo, as_aware
from tgparser.db.settings_store import ScanSettings
from tgparser.ratelimit.guard import AccountFlagged, FloodGuard, ScanAborted

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[str], Awaitable[None]]

# Как часто сбрасывать накопленное в БД.
FLUSH_EVERY = 50

# Сколько сообщений пересылать одним вызовом. Telegram принимает до 100,
# берём с запасом, чтобы одна неудача стоила меньше.
FORWARD_BATCH = 20

# Как часто отмечаться в логах внутри одного чата.
LOG_EVERY_PAGES = 10


@dataclass(slots=True)
class ChatReport:
    chat_id: int
    title: str
    kind: str
    participants_count: int | None = None
    participants_visible: bool | None = None
    collected: int = 0
    scanned_messages: int = 0
    forwarded: int = 0
    anonymized: int = 0
    skipped: str | None = None
    error: str | None = None

    @property
    def done(self) -> bool:
        return self.skipped is None and self.error is None


@dataclass(slots=True)
class ScanReport:
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None
    dialogs_total: int = 0
    chats: list[ChatReport] = field(default_factory=list)
    aborted: bool = False
    abort_reason: str | None = None
    flagged: bool = False

    @property
    def new_leads(self) -> int:
        return sum(c.collected for c in self.chats)

    # Синоним для читаемости в тестах и отчётах.
    @property
    def collected_total(self) -> int:
        return self.new_leads

    @property
    def scanned_messages(self) -> int:
        return sum(c.scanned_messages for c in self.chats)

    @property
    def forwarded(self) -> int:
        return sum(c.forwarded for c in self.chats)

    @property
    def anonymized(self) -> int:
        return sum(c.anonymized for c in self.chats)

    @property
    def chats_scanned(self) -> int:
        return sum(1 for c in self.chats if c.done)

    @property
    def chats_skipped(self) -> int:
        return sum(1 for c in self.chats if c.skipped)


class Scanner:
    def __init__(
        self,
        client: Any,
        guard: FloodGuard,
        settings: ScanSettings,
        db: Any,
        account_id: int,
        owner_id: int,
        self_id: int,
        archive: Archive,
        on_progress: ProgressCallback | None = None,
        on_status: ProgressCallback | None = None,
    ) -> None:
        self._client = client
        self._guard = guard
        self._settings = settings
        self._db = db
        self._account_id = account_id
        self._owner_id = owner_id
        self._self_id = self_id
        self._archive = archive
        self._on_progress = on_progress
        self._on_status = on_status
        self._position = ""
        self._seen: set[int] = set()
        self._pending: list[CollectedUser] = []
        # Очередь на пересылку: (lead_id, message_id, peer). Наполняется уже
        # после того, как лид записан, поэтому медленная пересылка не может
        # задержать сохранение собранного.
        self._to_forward: list[tuple[int, int, Any]] = []
        self._report = ScanReport()
        self._current: ChatReport | None = None

    async def _progress(self, text: str) -> None:
        if self._on_progress is not None:
            try:
                await self._on_progress(text)
            except Exception:
                logger.debug("Не удалось отправить прогресс", exc_info=True)

    async def _status(self, text: str) -> None:
        """Обновить живую строку состояния.

        Без неё на крупном чате сообщение в боте часами не менялось, и обход
        выглядел зависшим.
        """
        if self._on_status is not None:
            try:
                await self._on_status(text)
            except Exception:
                logger.debug("Не удалось обновить статус", exc_info=True)

    async def run(self) -> ScanReport:
        async with self._db.session() as session:
            self._seen = await LeadRepo(session, self._owner_id).all_user_ids()
        logger.info("В базе уже %s пользователей", len(self._seen))

        try:
            dialogs = await self._collect_dialogs()
            self._report.dialogs_total = len(dialogs)
            await self._progress(f"Найдено чатов для обхода: {len(dialogs)}")

            for index, (entity, marked_id) in enumerate(dialogs, start=1):
                report = await self._scan_dialog(entity, marked_id, index, len(dialogs))
                if report is not None:
                    self._report.chats.append(report)
        except AccountFlagged as exc:
            self._report.aborted = True
            self._report.flagged = True
            self._report.abort_reason = str(exc)
        except ScanAborted as exc:
            self._report.aborted = True
            self._report.abort_reason = str(exc)
        finally:
            await self._finish_writes()
            self._report.finished_at = datetime.now(UTC)

        return self._report

    # --- перебор диалогов ---

    async def _collect_dialogs(self) -> list[tuple[Any, int]]:
        """Группы, супергруппы, форумы и каналы из списка диалогов аккаунта."""
        found: list[tuple[Any, int]] = []
        async for dialog in self._client.iter_dialogs():
            entity = dialog.entity
            if dialog.is_user:
                continue
            marked_id = get_peer_id(entity)
            if self._is_excluded(marked_id, getattr(entity, "username", None)):
                continue
            found.append((entity, marked_id))
        return found

    def _is_excluded(self, marked_id: int, username: str | None) -> bool:
        s = self._settings
        if s.included_chats:
            return not chat_matches(marked_id, username, s.included_chats)
        return chat_matches(marked_id, username, s.excluded_chats)

    async def _scan_dialog(
        self, entity: Any, marked_id: int, index: int, total: int
    ) -> ChatReport | None:
        try:
            target = await inspect(self._client, self._guard, entity, marked_id)
        except (AccountFlagged, ScanAborted):
            raise
        except RPCError as exc:
            logger.warning("Пропускаю %s: %s", marked_id, exc)
            return ChatReport(
                chat_id=marked_id,
                title=str(getattr(entity, "title", marked_id)),
                kind="unknown",
                error=str(exc),
            )
        if target is None:
            return None

        report = ChatReport(
            chat_id=target.chat_id,
            title=target.title,
            kind=target.kind.value,
            participants_count=target.participants_count,
            participants_visible=target.participants_visible,
        )
        self._current = report

        if (
            self._settings.min_participants
            and (target.participants_count or 0) < self._settings.min_participants
        ):
            report.skipped = f"участников меньше {self._settings.min_participants}"
            return report

        self._position = f"[{index}/{total}]"
        await self._progress(
            f"[{index}/{total}] {target.title} — {target.kind.value}, "
            f"участники {'видны' if target.participants_visible else 'скрыты'}"
        )
        await self._status(f"{self._position} {target.title} · начинаю")

        async with self._db.session() as session:
            state = await ChatStateRepo(session).get_or_create(
                self._account_id, target.chat_id, target.title, target.kind.value
            )
            state.participants_visible = target.participants_visible
            state.participants_count = target.participants_count
            state_id = state.id
            resume_from = state.oldest_message_id
            roster_offset = state.roster_offset
            roster_done = state.roster_done
            history_done = state.history_done

        try:
            if target.is_channel:
                await self._scan_channel(target, report, resume_from, history_done, state_id)
            else:
                if self._settings.collect_roster and target.participants_visible and not roster_done:
                    await self._scan_roster(target, report, roster_offset, state_id)
                if self._settings.collect_history and not history_done:
                    await self._scan_history(
                        target, report, resume_from, state_id, target.entity
                    )
        except (AccountFlagged, ScanAborted):
            await self._save_state(state_id, error="прогон прерван")
            raise
        except ChannelPrivateError:
            report.error = "нет доступа"
        except RPCError as exc:
            logger.warning("Ошибка на чате %s: %s", target.title, exc)
            report.error = str(exc)

        # Дописываем остаток и пересылаем карточки, пока отчёт этого
        # чата ещё актуален.
        await self._finish_writes()
        await self._save_state(state_id, collected=report.collected)
        logger.info(
            "Чат %r: собрано %s, просмотрено сообщений %s%s",
            target.title, report.collected, report.scanned_messages,
            f", пропущен: {report.skipped}" if report.skipped else "",
        )
        return report

    async def _scan_channel(
        self,
        target: ChatTarget,
        report: ChatReport,
        resume_from: int | None,
        history_done: bool,
        state_id: int,
    ) -> None:
        """У каналов подписчиков API не отдаёт — собираем авторов комментариев."""
        if not self._settings.collect_comments:
            report.skipped = "сбор комментариев выключен"
            return
        if not target.linked_chat_id:
            report.skipped = "у канала нет чата обсуждений"
            return
        if history_done:
            report.skipped = "уже обойдён"
            return

        try:
            discussion = await self._client.get_entity(target.linked_chat_id)
        except (RPCError, ValueError) as exc:
            report.skipped = f"чат обсуждений недоступен: {exc}"
            return

        # Комментарии всех постов лежат в истории привязанной группы, поэтому
        # один проход по ней дешевле, чем getDiscussionMessage на каждый пост.
        await self._scan_history(
            target,
            report,
            resume_from,
            state_id,
            discussion,
            source=SourceKind.COMMENT,
            history_peer_id=get_peer_id(discussion),
        )

    # --- стратегии сбора ---

    async def _scan_history(
        self,
        target: ChatTarget,
        report: ChatReport,
        resume_from: int | None,
        state_id: int | None,
        peer: Any,
        source: SourceKind = SourceKind.HISTORY,
        history_peer_id: int | None = None,
    ) -> None:
        cutoff = cutoff_datetime(self._settings.history_depth_days)
        offset_id = resume_from or 0
        batch = max(1, min(100, self._settings.history_batch_size))

        topic_titles = self._topic_titles(target)
        excluded_topics = self._excluded_topic_ids(target)
        allowed_topics = self._allowed_topic_ids(target)

        oldest_seen = offset_id
        pages = 0
        while True:
            result = await self._guard.call(
                "history",
                self._client,
                GetHistoryRequest(
                    peer=peer,
                    offset_id=offset_id,
                    offset_date=None,
                    add_offset=0,
                    limit=batch,
                    max_id=0,
                    min_id=0,
                    hash=0,
                ),
            )
            messages = getattr(result, "messages", None) or []
            if not messages:
                break

            # Ответ getHistory приносит объекты авторов — отдельные запросы
            # на профили не нужны.
            users_by_id = {u.id: u for u in (getattr(result, "users", None) or [])}

            reached_cutoff = False
            for message in messages:
                oldest_seen = message.id
                report.scanned_messages += 1

                message_date = as_aware(getattr(message, "date", None))
                if cutoff is not None and message_date is not None and message_date < cutoff:
                    reached_cutoff = True
                    break

                if isinstance(message, MessageService):
                    continue

                topic_id = topic_id_of(message) if target.is_forum else None
                if topic_id is not None:
                    if topic_id in excluded_topics:
                        continue
                    if allowed_topics is not None and topic_id not in allowed_topics:
                        continue

                user = self._sender_of(message, users_by_id)
                if user is None:
                    continue

                await self._collect(
                    user,
                    target,
                    message,
                    source=source,
                    topic_title=topic_titles.get(topic_id) if topic_id else None,
                    peer=peer,
                    history_peer_id=history_peer_id,
                    report=report,
                )

            offset_id = oldest_seen
            pages += 1
            if state_id is not None:
                await self._save_state(state_id, oldest_message_id=oldest_seen)

            # Крупный чат идёт часами, и без периодической отметки логи
            # выглядят так, будто прогон висит.
            if pages % LOG_EVERY_PAGES == 0:
                logger.info(
                    "%r: страниц %s, сообщений %s, собрано %s, до сообщения %s",
                    target.title,
                    pages,
                    report.scanned_messages,
                    report.collected,
                    oldest_seen,
                )
                await self._status(
                    f"{self._position} {target.title} · сообщений "
                    f"{report.scanned_messages}, найдено {report.collected}, "
                    f"всего за прогон {self._report.new_leads + report.collected}"
                )

            if reached_cutoff or len(messages) < batch:
                if state_id is not None:
                    await self._save_state(state_id, history_done=True)
                break

    def _sender_of(self, message: Any, users_by_id: dict[int, Any]) -> Any | None:
        from_id = getattr(message, "from_id", None)
        if not isinstance(from_id, PeerUser):
            # Анонимные админы и посты от имени канала — не пользователи.
            return None
        user = users_by_id.get(from_id.user_id)
        if user is None:
            return None
        skip = classify_user(
            user,
            skip_bots=self._settings.skip_bots,
            skip_deleted=self._settings.skip_deleted,
            self_id=self._self_id,
            seen=self._seen,
        )
        return None if skip is not None else user

    async def _scan_roster(
        self, target: ChatTarget, report: ChatReport, offset: int, state_id: int
    ) -> None:
        """Перебор участников. Включается вручную: главный триггер PeerFlood."""
        if target.kind is ChatKind.GROUP:
            await self._scan_roster_basic(target, report)
            await self._save_state(state_id, roster_done=True)
            return

        limit = 200
        hard_cap = min(self._settings.roster_limit_per_chat, 10_000)
        while offset < hard_cap:
            result = await self._guard.call(
                "roster",
                self._client,
                GetParticipantsRequest(
                    channel=target.entity,
                    filter=ChannelParticipantsSearch(""),
                    offset=offset,
                    limit=limit,
                    hash=0,
                ),
            )
            users = getattr(result, "users", None) or []
            if not users:
                break
            for user in users:
                skip = classify_user(
                    user,
                    skip_bots=self._settings.skip_bots,
                    skip_deleted=self._settings.skip_deleted,
                    self_id=self._self_id,
                    seen=self._seen,
                )
                if skip is None:
                    await self._collect(
                        user, target, None, source=SourceKind.ROSTER, report=report
                    )
            offset += len(users)
            await self._save_state(state_id, roster_offset=offset)
            if len(users) < limit:
                break
        await self._save_state(state_id, roster_done=True)

    async def _scan_roster_basic(self, target: ChatTarget, report: ChatReport) -> None:
        """У обычных групп участники уже приехали вместе с метаданными."""
        for user in getattr(target, "preloaded_users", None) or []:
            skip = classify_user(
                user,
                skip_bots=self._settings.skip_bots,
                skip_deleted=self._settings.skip_deleted,
                self_id=self._self_id,
                seen=self._seen,
            )
            if skip is None:
                await self._collect(
                    user, target, None, source=SourceKind.ROSTER, report=report
                )

    # --- запись ---

    async def _collect(
        self,
        user: Any,
        target: ChatTarget,
        message: Any | None,
        source: SourceKind,
        report: ChatReport,
        topic_title: str | None = None,
        peer: Any | None = None,
        history_peer_id: int | None = None,
    ) -> None:
        username = active_username(user)
        link_chat_id = history_peer_id or target.chat_id
        link_username = target.username if history_peer_id is None else None

        collected = CollectedUser(
            tg_user_id=user.id,
            username=username,
            first_name=getattr(user, "first_name", None),
            last_name=getattr(user, "last_name", None),
            phone=getattr(user, "phone", None),
            is_premium=bool(getattr(user, "premium", False)),
            chat_id=target.chat_id,
            chat_title=target.title,
            chat_username=target.username,
            topic_title=topic_title,
            source=source,
        )
        if message is not None:
            collected.message_id = message.id
            collected.message_date = as_aware(getattr(message, "date", None))
            collected.snippet = snippet(getattr(message, "message", None))
            collected.message_link = message_link(
                message.id,
                chat_id=link_chat_id,
                chat_username=link_username,
                topic_id=topic_id_of(message) if target.is_forum else None,
            )

        self._seen.add(user.id)
        report.collected += 1

        needs_forward = (
            self._settings.forward_untagged
            and not username
            and message is not None
            and peer is not None
        )
        collected.forward_peer = peer if needs_forward else None
        self._pending.append(collected)

        if len(self._pending) >= FLUSH_EVERY:
            await self._flush()

    async def _flush(self) -> None:
        """Записать собранное. Только БД, без сетевых вызовов.

        Пересылка вынесена отдельно: держать транзакцию открытой, пока идут
        медленные запросы к Telegram, значит терять всю пачку при обрыве и
        не показывать пользователю ничего до конца пересылок.
        """
        if not self._pending:
            return
        batch = self._pending
        self._pending = []

        async with self._db.session() as session:
            repo = LeadRepo(session, self._owner_id)
            for collected in batch:
                lead = await repo.add(collected)
                if lead is None:
                    continue
                if collected.forward_peer is not None and collected.message_id:
                    self._to_forward.append(
                        (lead.id, collected.message_id, collected.forward_peer)
                    )
        logger.info(
            "Записано %s, в очереди на пересылку %s", len(batch), len(self._to_forward)
        )

    async def _drain_forwards(self) -> None:
        """Переслать накопленные карточки пачками — по одному вызову на чат."""
        if not self._to_forward:
            return

        queue = self._to_forward
        self._to_forward = []
        report = self._current

        grouped: dict[int, tuple[Any, list[tuple[int, int]]]] = {}
        for lead_id, message_id, peer in queue:
            key = get_peer_id(peer)
            grouped.setdefault(key, (peer, []))[1].append((lead_id, message_id))

        for peer, items in grouped.values():
            for start in range(0, len(items), FORWARD_BATCH):
                chunk = items[start : start + FORWARD_BATCH]
                results = await self._archive.forward_many(
                    [message_id for _, message_id in chunk], peer
                )
                async with self._db.session() as session:
                    repo = LeadRepo(session, self._owner_id)
                    for (lead_id, _), result in zip(chunk, results, strict=False):
                        if not result.ok:
                            continue
                        lead = await session.get(Lead, lead_id)
                        if lead is None:
                            continue
                        await repo.set_archive(lead, result.link, result.anonymized)
                        if report is not None:
                            report.forwarded += 1
                            if result.anonymized:
                                report.anonymized += 1

    async def _finish_writes(self) -> None:
        """Дописать буфер и разгрести очередь пересылок.

        Пересылка может упереться в бюджет или FloodWait, но собранное к этому
        моменту уже лежит в базе, поэтому её неудача ничего не теряет.
        """
        await self._flush()
        try:
            await self._drain_forwards()
        except (AccountFlagged, ScanAborted):
            raise
        except Exception:
            logger.exception("Не удалось переслать часть карточек")

    async def _save_state(self, state_id: int, **updates: Any) -> None:
        if not updates:
            return
        async with self._db.session() as session:
            state = await session.get(ChatState, state_id)
            if state is None:
                return
            for key, value in updates.items():
                if key == "collected":
                    state.collected = value
                elif key == "error":
                    state.last_error = value
                else:
                    setattr(state, key, value)
            await ChatStateRepo(session).mark_scanned(state)

    # --- топики форумов ---

    def _topic_titles(self, target: ChatTarget) -> dict[int, str]:
        return {t.id: t.title for t in (target.topics or [])}

    def _excluded_topic_ids(self, target: ChatTarget) -> set[int]:
        return {
            t.id
            for t in (target.topics or [])
            if is_topic_excluded(t.title, self._settings.excluded_topic_titles)
        }

    def _allowed_topic_ids(self, target: ChatTarget) -> set[int] | None:
        """Непустое множество — обходим только эти топики."""
        if not self._settings.forum_busiest_topic_only or not target.topics:
            return None
        busiest = target.busiest_topic
        return {busiest.id} if busiest is not None else None
