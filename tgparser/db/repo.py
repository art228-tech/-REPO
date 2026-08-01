"""Доступ к данным: дедуп лидов, чекпоинты обхода, аккаунты."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tgparser.db.models import (
    Account,
    ChatState,
    Lead,
    LeadStatus,
    SourceKind,
    utcnow,
)


@dataclass(slots=True)
class CollectedUser:
    """Пользователь, извлечённый из чата, до записи в БД."""

    tg_user_id: int
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    phone: str | None = None
    is_premium: bool = False

    chat_id: int | None = None
    chat_title: str | None = None
    chat_username: str | None = None
    topic_title: str | None = None
    message_id: int | None = None
    message_link: str | None = None
    message_date: datetime | None = None
    snippet: str | None = None
    source: SourceKind = SourceKind.HISTORY

    @property
    def has_username(self) -> bool:
        return bool(self.username)


def as_aware(value: datetime | None) -> datetime | None:
    """SQLite отдаёт naive datetime — приводим к UTC-aware."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


class LeadRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def exists(self, tg_user_id: int) -> bool:
        found = await self.session.scalar(
            select(Lead.id).where(Lead.tg_user_id == tg_user_id).limit(1)
        )
        return found is not None

    async def add(self, user: CollectedUser) -> Lead | None:
        """Записать нового пользователя. ``None``, если он уже в базе.

        Дедуп глобальный: повторная встреча в другом чате ничего не создаёт.
        """
        if await self.exists(user.tg_user_id):
            return None
        lead = Lead(
            tg_user_id=user.tg_user_id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
            phone=user.phone,
            is_premium=user.is_premium,
            source=user.source.value,
            status=LeadStatus.NEW.value,
            chat_id=user.chat_id,
            chat_title=user.chat_title,
            chat_username=user.chat_username,
            topic_title=user.topic_title,
            message_id=user.message_id,
            message_link=user.message_link,
            message_date=user.message_date,
            snippet=user.snippet,
        )
        self.session.add(lead)
        await self.session.flush()
        return lead

    async def add_manual(self, username: str, note: str | None = None) -> tuple[Lead, bool]:
        """Ручное добавление тега. Возвращает (лид, создан_ли)."""
        clean = username.strip().lstrip("@")
        existing = await self.session.scalar(
            select(Lead).where(func.lower(Lead.username) == clean.lower())
        )
        if existing is not None:
            if note:
                existing.note = note
                await self.session.flush()
            return existing, False
        lead = Lead(
            tg_user_id=None,
            username=clean,
            source=SourceKind.MANUAL.value,
            status=LeadStatus.NEW.value,
            note=note,
        )
        self.session.add(lead)
        await self.session.flush()
        return lead, True

    async def all_user_ids(self) -> set[int]:
        """Все известные tg_user_id — грузится один раз на прогон.

        Держать множество в памяти дешевле, чем спрашивать базу на каждое
        сообщение: в активном чате это десятки тысяч проверок.
        """
        rows = await self.session.execute(
            select(Lead.tg_user_id).where(Lead.tg_user_id.is_not(None))
        )
        return {row[0] for row in rows}

    async def set_archive(self, lead: Lead, link: str | None, anonymized: bool) -> None:
        lead.archive_link = link
        lead.archive_anonymized = anonymized
        await self.session.flush()

    async def count(self) -> int:
        return await self.session.scalar(select(func.count()).select_from(Lead)) or 0

    async def stats(self) -> dict[str, int]:
        total = await self.count()
        tagged = (
            await self.session.scalar(
                select(func.count()).select_from(Lead).where(Lead.username.is_not(None))
            )
            or 0
        )
        archived = (
            await self.session.scalar(
                select(func.count()).select_from(Lead).where(Lead.archive_link.is_not(None))
            )
            or 0
        )
        anonymized = (
            await self.session.scalar(
                select(func.count())
                .select_from(Lead)
                .where(Lead.archive_anonymized.is_(True))
            )
            or 0
        )
        chats = (
            await self.session.scalar(
                select(func.count(func.distinct(Lead.chat_id))).where(Lead.chat_id.is_not(None))
            )
            or 0
        )
        manual = (
            await self.session.scalar(
                select(func.count())
                .select_from(Lead)
                .where(Lead.source == SourceKind.MANUAL.value)
            )
            or 0
        )
        return {
            "leads": total,
            "with_username": tagged,
            "without_username": total - tagged,
            "archived_cards": archived,
            "anonymized_cards": anonymized,
            "chats": chats,
            "manual": manual,
        }


class ChatStateRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_or_create(
        self, account_id: int, chat_id: int, title: str | None, kind: str
    ) -> ChatState:
        state = await self.session.scalar(
            select(ChatState).where(
                ChatState.account_id == account_id, ChatState.chat_id == chat_id
            )
        )
        if state is None:
            state = ChatState(account_id=account_id, chat_id=chat_id, title=title, kind=kind)
            self.session.add(state)
            await self.session.flush()
        else:
            state.title = title or state.title
            state.kind = kind
        return state

    async def mark_scanned(self, state: ChatState) -> None:
        state.last_scanned_at = utcnow()
        await self.session.flush()

    async def for_account(self, account_id: int) -> list[ChatState]:
        rows = await self.session.scalars(
            select(ChatState)
            .where(ChatState.account_id == account_id)
            .order_by(ChatState.id)
        )
        return list(rows)

    async def reset(self, account_id: int) -> int:
        """Сбросить чекпоинты, чтобы следующий прогон начался с нуля."""
        states = await self.for_account(account_id)
        for state in states:
            state.oldest_message_id = None
            state.roster_offset = 0
            state.roster_done = False
            state.history_done = False
            state.last_error = None
        await self.session.flush()
        return len(states)


class AccountRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_active(self) -> list[Account]:
        rows = await self.session.scalars(
            select(Account).where(Account.is_active.is_(True)).order_by(Account.id)
        )
        return list(rows)

    async def first_active(self) -> Account | None:
        accounts = await self.get_active()
        return accounts[0] if accounts else None

    async def get_by_phone(self, phone: str) -> Account | None:
        return await self.session.scalar(select(Account).where(Account.phone == phone))

    async def get(self, account_id: int) -> Account | None:
        return await self.session.get(Account, account_id)

    async def upsert_session(
        self,
        phone: str,
        session_enc: bytes,
        tg_user_id: int | None,
        username: str | None,
        proxy: str | None = None,
    ) -> Account:
        account = await self.get_by_phone(phone)
        if account is None:
            account = Account(
                phone=phone,
                session_enc=session_enc,
                tg_user_id=tg_user_id,
                username=username,
                proxy=proxy,
            )
            self.session.add(account)
        else:
            account.session_enc = session_enc
            account.tg_user_id = tg_user_id
            account.username = username
            account.proxy = proxy
            account.is_active = True
            account.blocked_until = None
            account.block_reason = None
        await self.session.flush()
        return account

    async def delete(self, account: Account) -> None:
        await self.session.delete(account)
        await self.session.flush()

    async def block(self, account: Account, hours: int, reason: str) -> None:
        account.blocked_until = utcnow() + timedelta(hours=hours)
        account.block_reason = reason
        await self.session.flush()

    async def unblock(self, account: Account) -> None:
        account.blocked_until = None
        account.block_reason = None
        await self.session.flush()

    @staticmethod
    def is_blocked(account: Account, now: datetime | None = None) -> bool:
        blocked_until = as_aware(account.blocked_until)
        if blocked_until is None:
            return False
        return blocked_until > (now or utcnow())
