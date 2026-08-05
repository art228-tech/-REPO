"""
Shared SQLAlchemy models for all bots.
"""
from datetime import datetime
from typing import Optional
from sqlalchemy import (
    BigInteger, Boolean, DateTime, Float, ForeignKey,
    Integer, String, Text, func, JSON
)
from sqlalchemy.ext.asyncio import AsyncAttrs, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
import os


DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://botuser:botpassword@postgres:5432/botdb")

engine = create_async_engine(DATABASE_URL, echo=False, pool_pre_ping=True)
async_session = async_sessionmaker(engine, expire_on_commit=False)


class Base(AsyncAttrs, DeclarativeBase):
    pass


# ─────────────────────────────────────────────
# Welcome Bot (child bot managed by constructor)
# ─────────────────────────────────────────────

class WelcomeBot(Base):
    __tablename__ = "welcome_bots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    username: Mapped[str] = mapped_column(String(200), nullable=True)
    channel_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)   # source channel
    channel_title: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    delay_seconds: Mapped[int] = mapped_column(Integer, default=0)  # delay after join before first msg
    reminder_seconds: Mapped[int] = mapped_column(Integer, default=3600)  # resend if stuck
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    steps: Mapped[list["ScenarioStep"]] = relationship(
        "ScenarioStep", back_populates="bot", cascade="all, delete-orphan",
        order_by="ScenarioStep.position"
    )
    users: Mapped[list["BotUser"]] = relationship("BotUser", back_populates="bot")


# ─────────────────────────────────────────────
# Scenario Step
# ─────────────────────────────────────────────

class ScenarioStep(Base):
    """
    One step in the welcome funnel. Can be:
    - 'message'  : send a message, optionally wait for user to click a button or send text
    - 'op'       : mandatory subscription check
    - 'wait'     : timed delay with a waiting text before next step
    """
    __tablename__ = "scenario_steps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("welcome_bots.id"), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)   # order in funnel
    step_type: Mapped[str] = mapped_column(String(20), nullable=False)  # message | op | wait

    # Forwarded message data (stored as JSON: {chat_id, message_id, file_id, ...})
    message_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # For 'message' step: does it have inline buttons that the user must click?
    has_buttons: Mapped[bool] = mapped_column(Boolean, default=False)

    # Delay AFTER this step completes before next step starts (seconds, 0 = immediate)
    delay_after: Mapped[int] = mapped_column(Integer, default=0)

    # Waiting text shown during delay_after (if delay_after > 0)
    waiting_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    bot: Mapped["WelcomeBot"] = relationship("WelcomeBot", back_populates="steps")
    sponsors: Mapped[list["Sponsor"]] = relationship(
        "Sponsor", back_populates="step", cascade="all, delete-orphan"
    )


# ─────────────────────────────────────────────
# Sponsors (for OP steps)
# ─────────────────────────────────────────────

class Sponsor(Base):
    __tablename__ = "sponsors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    step_id: Mapped[int] = mapped_column(ForeignKey("scenario_steps.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    channel_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)  # 0 = no check

    step: Mapped["ScenarioStep"] = relationship("ScenarioStep", back_populates="sponsors")


# ─────────────────────────────────────────────
# Bot Users
# ─────────────────────────────────────────────

class BotUser(Base):
    __tablename__ = "bot_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("welcome_bots.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    username: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    full_name: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)

    # Tracking
    current_step: Mapped[int] = mapped_column(Integer, default=0)
    completed: Mapped[bool] = mapped_column(Boolean, default=False)
    join_ref: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)   # referral link

    # Message IDs sent to user (to delete later)
    sent_message_ids: Mapped[Optional[list]] = mapped_column(JSON, default=list)

    joined_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_activity: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    bot: Mapped["WelcomeBot"] = relationship("WelcomeBot", back_populates="users")
    step_completions: Mapped[list["UserStepCompletion"]] = relationship(
        "UserStepCompletion", back_populates="user_entry"
    )


class UserStepCompletion(Base):
    __tablename__ = "user_step_completions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bot_user_id: Mapped[int] = mapped_column(ForeignKey("bot_users.id"), nullable=False)
    step_id: Mapped[int] = mapped_column(ForeignKey("scenario_steps.id"), nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user_entry: Mapped["BotUser"] = relationship("BotUser", back_populates="step_completions")


async def create_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
