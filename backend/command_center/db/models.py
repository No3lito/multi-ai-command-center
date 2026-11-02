"""SQLAlchemy models. Schema changes go through Alembic migrations."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Principal(Base):
    __tablename__ = "principals"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))
    display_name: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(16), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint("kind in ('owner','human','agent','external','system')", name="principal_kind"),
        Index("one_owner", "kind", unique=True, postgresql_where="kind = 'owner'"),
    )


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    principal_id: Mapped[str] = mapped_column(ForeignKey("principals.id"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Room(Base):
    __tablename__ = "rooms"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("principals.id"))
    last_seq: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RoomMember(Base):
    __tablename__ = "room_members"

    room_id: Mapped[str] = mapped_column(ForeignKey("rooms.id", ondelete="CASCADE"), primary_key=True)
    principal_id: Mapped[str] = mapped_column(ForeignKey("principals.id"), primary_key=True)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (Index("members_by_principal", "principal_id", "room_id"),)


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    room_id: Mapped[str] = mapped_column(ForeignKey("rooms.id", ondelete="CASCADE"))
    seq: Mapped[int] = mapped_column(BigInteger)
    sender_id: Mapped[str] = mapped_column(ForeignKey("principals.id"))
    kind: Mapped[str] = mapped_column(String(32))
    thread_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    reply_to: Mapped[str | None] = mapped_column(String(40), nullable=True)
    mentions: Mapped[list[str]] = mapped_column(JSONB, default=list)
    body_text: Mapped[str] = mapped_column(Text)
    body_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    task_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    usage: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("room_id", "seq", name="messages_room_seq"),
        UniqueConstraint("sender_id", "idempotency_key", name="messages_sender_idempotency"),
        CheckConstraint("seq >= 1", name="messages_seq_positive"),
    )


class AuditEvent(Base):
    """Append-only security log. Hash chaining arrives in Milestone C."""

    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    actor_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    action: Mapped[str] = mapped_column(String(64))
    target: Mapped[str | None] = mapped_column(String(80), nullable=True)
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    client_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ---------------------------------------------------------------- Milestone B


class AgentProfile(Base):
    """Configuration of an AI agent. The agent itself is a Principal of kind 'agent'."""

    __tablename__ = "agent_profiles"

    principal_id: Mapped[str] = mapped_column(ForeignKey("principals.id"), primary_key=True)
    role: Mapped[str] = mapped_column(String(80), default="Assistant")
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(100))
    system_prompt: Mapped[str] = mapped_column(Text, default="")
    max_output_tokens: Mapped[int] = mapped_column(Integer, default=1024)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint("provider in ('anthropic','openai','xai','simulated')", name="agent_provider"),
        CheckConstraint("max_output_tokens between 16 and 8192", name="agent_max_output_tokens"),
    )


class Run(Base):
    """A unit of coordinated work in a room. State is durable so a restart resumes it."""

    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    room_id: Mapped[str] = mapped_column(ForeignKey("rooms.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(24), default="queued")
    step: Mapped[str] = mapped_column(String(16))
    goal: Mapped[str] = mapped_column(Text)
    planner_id: Mapped[str | None] = mapped_column(ForeignKey("principals.id"), nullable=True)
    critic_id: Mapped[str | None] = mapped_column(ForeignKey("principals.id"), nullable=True)
    agent_id: Mapped[str | None] = mapped_column(ForeignKey("principals.id"), nullable=True)
    # Every run belongs to a tree started by one human action. Limits and budget apply per tree.
    root_run_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    trigger_message_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    last_message_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    hop: Mapped[int] = mapped_column(Integer, default=0)
    turn_count: Mapped[int] = mapped_column(Integer, default=0)
    max_turns: Mapped[int] = mapped_column(Integer, default=8)
    budget_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6))
    spent_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=Decimal(0))
    simulated: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("principals.id"))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint("kind in ('collab','reply')", name="run_kind"),
        CheckConstraint(
            "status in ('queued','running','completed','failed','cancelled','budget_exceeded')",
            name="run_status",
        ),
        Index("runs_active", "status", "created_at", postgresql_where="status in ('queued','running')"),
        Index("runs_by_room", "room_id", "created_at"),
        Index("runs_by_root", "root_run_id"),
    )


class SpendCap(Base):
    """Instance-wide spending cap. Reservations are taken atomically before every paid call."""

    __tablename__ = "spend_caps"

    scope: Mapped[str] = mapped_column(String(40), primary_key=True)
    cap_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6))
    spent_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=Decimal(0))
    reserved_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=Decimal(0))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        # No "spent <= cap" constraint: true spend is always recorded, even if an estimate was
        # exceeded. Reservations are refused once spent + reserved reaches the cap.
        CheckConstraint("spent_usd >= 0 and reserved_usd >= 0", name="spend_cap_non_negative"),
    )


class BudgetReservation(Base):
    __tablename__ = "budget_reservations"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("runs.id", ondelete="SET NULL"), nullable=True)
    scope: Mapped[str] = mapped_column(String(40))
    amount_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6))
    actual_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="reserved")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint("status in ('reserved','settled','released')", name="reservation_status"),
        Index("reservations_open", "status", "created_at", postgresql_where="status = 'reserved'"),
    )


class UsageEntry(Base):
    """One model call. simulated=true rows are local stand-ins and cost nothing."""

    __tablename__ = "usage_ledger"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("runs.id", ondelete="SET NULL"), nullable=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey("principals.id"))
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(100))
    input_tokens: Mapped[int] = mapped_column(Integer)
    output_tokens: Mapped[int] = mapped_column(Integer)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6))
    simulated: Mapped[bool] = mapped_column(Boolean)
    reservation_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    message_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
