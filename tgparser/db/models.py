"""Схема БД."""

from __future__ import annotations

import enum
from datetime import UTC, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class SourceKind(enum.StrEnum):
    """Откуда получена запись."""

    ROSTER = "roster"  # из списка участников
    HISTORY = "history"  # автор сообщения в чате
    COMMENT = "comment"  # автор комментария под постом канала
    MANUAL = "manual"  # добавлено вручную через бота


class ChatKind(enum.StrEnum):
    GROUP = "group"
    SUPERGROUP = "supergroup"
    FORUM = "forum"
    CHANNEL = "channel"


class LeadStatus(enum.StrEnum):
    NEW = "new"
    CONTACTED = "contacted"
    REPLIED = "replied"
    IRRELEVANT = "irrelevant"


class Account(Base):
    """Подключённый Telegram-аккаунт (userbot).

    ``owner_id`` — это id пользователя бота, который аккаунт подключил.
    Бот многопользовательский: чужие аккаунты, настройки и записи не должны
    пересекаться, поэтому владелец есть у каждой таблицы с данными.
    """

    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, index=True)
    phone: Mapped[str] = mapped_column(String(32))
    tg_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    session_enc: Mapped[bytes] = mapped_column(LargeBinary)
    proxy: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Свои ключи приложения. Telegram выдаёт один api_id на номер, поэтому у
    # каждого аккаунта он может быть собственным — тогда ограничения на чужом
    # ключе не задевают остальных пользователей бота. Пусто — берём общие
    # ключи из окружения.
    api_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    api_hash_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    archive_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    # Circuit breaker: до какого момента аккаунт выведен из работы после PeerFlood.
    blocked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    block_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)

    chat_states: Mapped[list[ChatState]] = relationship(
        back_populates="account", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("owner_id", "phone", name="uq_account_owner_phone"),
    )


class Lead(Base):
    """Собранный пользователь.

    Один человек — одна строка, независимо от того, в скольких чатах встретился.
    Дедуп держится на паре (владелец, ``tg_user_id``); для записей, добавленных
    вручную, id пустой, и там уникальность обеспечивается по тегу.
    """

    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, index=True)
    tg_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    first_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    is_premium: Mapped[bool] = mapped_column(Boolean, default=False)

    source: Mapped[str] = mapped_column(String(16), default=SourceKind.HISTORY.value)
    status: Mapped[str] = mapped_column(String(16), default=LeadStatus.NEW.value, index=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Чат, в котором человек попался впервые.
    chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    chat_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    chat_username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    topic_title: Mapped[str | None] = mapped_column(String(255), nullable=True)

    message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    message_link: Mapped[str | None] = mapped_column(String(255), nullable=True)
    message_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    snippet: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Для безтеговых: ссылка на пересланную карточку в архивном канале.
    archive_link: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # True, если в пересылке пропала ссылка на автора (приватность «пересылки — никто»).
    archive_anonymized: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        UniqueConstraint("owner_id", "tg_user_id", name="uq_lead_owner_user"),
        Index("ix_leads_owner_username", "owner_id", "username"),
    )

    @property
    def display_name(self) -> str:
        parts = [p for p in (self.first_name, self.last_name) if p]
        if parts:
            return " ".join(parts)
        return self.username or str(self.tg_user_id or "")

    @property
    def tag(self) -> str | None:
        return f"@{self.username}" if self.username else None


class ChatState(Base):
    """Чекпоинт обхода одного чата — чтобы возобновляться с места обрыва."""

    __tablename__ = "chat_states"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), index=True
    )
    chat_id: Mapped[int] = mapped_column(BigInteger)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    kind: Mapped[str] = mapped_column(String(16), default=ChatKind.SUPERGROUP.value)

    participants_visible: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    participants_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Самый старый обработанный message_id: обход идёт от новых к старым.
    oldest_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    roster_offset: Mapped[int] = mapped_column(Integer, default=0)
    roster_done: Mapped[bool] = mapped_column(Boolean, default=False)
    history_done: Mapped[bool] = mapped_column(Boolean, default=False)

    collected: Mapped[int] = mapped_column(Integer, default=0)
    skipped: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_scanned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    account: Mapped[Account] = relationship(back_populates="chat_states")

    __table_args__ = (
        UniqueConstraint("account_id", "chat_id", name="uq_chat_state_account_chat"),
    )


class Setting(Base):
    """Настройки пользователя бота (key-value, значения в JSON)."""

    __tablename__ = "settings"

    owner_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
