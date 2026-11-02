"""Room and message persistence.

Ordering guarantee: a message's seq is taken by incrementing rooms.last_seq inside the
inserting transaction. That UPDATE row-locks the room until commit, so inserts into one
room are serialized and commit in seq order: a reader that has seen seq N can never later
discover an uncommitted N-1. Different rooms never block each other.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from command_center.db import models
from command_center.ids import new_id
from command_center.protocol import Body, CCMPMessage, MessageCreateIn, PrincipalOut, Sender

NOTIFY_CHANNEL = "ccmp_messages"


class RoomNotFound(Exception):
    pass


class RoomExists(Exception):
    pass


class NotAMember(Exception):
    pass


@dataclass(frozen=True)
class PostResult:
    message: CCMPMessage
    created: bool


def to_ccmp(msg: models.Message, sender: models.Principal) -> CCMPMessage:
    return CCMPMessage(
        id=msg.id,
        seq=msg.seq,
        room_id=msg.room_id,
        thread_id=msg.thread_id,
        sender=Sender(principal_id=sender.id, kind=sender.kind, display_name=sender.display_name),
        kind=msg.kind,
        reply_to=msg.reply_to,
        mentions=list(msg.mentions or []),
        body=Body(text=msg.body_text, data=msg.body_data),
        task_id=msg.task_id,
        correlation_id=msg.correlation_id,
        usage=msg.usage,
        created_at=msg.created_at,
    )


async def ensure_member(session: AsyncSession, room_id: str, principal_id: str) -> models.Room:
    room = await session.get(models.Room, room_id)
    if room is None:
        raise RoomNotFound(room_id)
    member = await session.get(models.RoomMember, (room_id, principal_id))
    if member is None:
        raise NotAMember(room_id)
    return room


async def list_rooms(session: AsyncSession, principal_id: str) -> list[tuple[models.Room, int]]:
    counted = aliased(models.RoomMember)
    member_count = (
        select(func.count())
        .select_from(counted)
        .where(counted.room_id == models.Room.id)
        .correlate(models.Room)
        .scalar_subquery()
    )
    stmt = (
        select(models.Room, member_count)
        .join(models.RoomMember, models.RoomMember.room_id == models.Room.id)
        .where(models.RoomMember.principal_id == principal_id)
        .order_by(models.Room.name)
    )
    return [(room, count) for room, count in (await session.execute(stmt)).all()]


async def room_members(session: AsyncSession, room_id: str) -> list[PrincipalOut]:
    stmt = (
        select(models.Principal)
        .join(models.RoomMember, models.RoomMember.principal_id == models.Principal.id)
        .where(models.RoomMember.room_id == room_id)
        .order_by(models.Principal.display_name)
    )
    return [
        PrincipalOut(id=p.id, kind=p.kind, display_name=p.display_name)
        for p in (await session.scalars(stmt)).all()
    ]


async def create_room(session: AsyncSession, name: str, creator: models.Principal) -> models.Room:
    existing = await session.scalar(select(models.Room).where(func.lower(models.Room.name) == name.lower()))
    if existing is not None:
        raise RoomExists(name)
    room = models.Room(id=new_id("room"), name=name, created_by=creator.id, last_seq=0)
    session.add(room)
    await session.flush()
    session.add(models.RoomMember(room_id=room.id, principal_id=creator.id))
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise RoomExists(name) from exc
    await session.refresh(room)
    return room


async def list_messages(
    session: AsyncSession, room_id: str, after_seq: int, limit: int
) -> tuple[list[CCMPMessage], bool]:
    stmt = (
        select(models.Message, models.Principal)
        .join(models.Principal, models.Principal.id == models.Message.sender_id)
        .where(models.Message.room_id == room_id, models.Message.seq > after_seq)
        .order_by(models.Message.seq)
        .limit(limit + 1)
    )
    rows = (await session.execute(stmt)).all()
    has_more = len(rows) > limit
    return [to_ccmp(m, p) for m, p in rows[:limit]], has_more


async def _find_by_key(session: AsyncSession, sender_id: str, key: str) -> CCMPMessage | None:
    stmt = (
        select(models.Message, models.Principal)
        .join(models.Principal, models.Principal.id == models.Message.sender_id)
        .where(models.Message.sender_id == sender_id, models.Message.idempotency_key == key)
    )
    row = (await session.execute(stmt)).first()
    return to_ccmp(row[0], row[1]) if row else None


async def post_message(
    session: AsyncSession, room_id: str, sender: models.Principal, data: MessageCreateIn
) -> PostResult:
    # Read plain values up front: a rollback below expires ORM objects, and touching an
    # expired attribute would trigger a lazy load, which is not allowed in async code.
    sender_id = sender.id
    existing = await _find_by_key(session, sender_id, data.idempotency_key)
    if existing is not None:
        if existing.room_id != room_id:
            raise ValueError("idempotency_key already used for a different room")
        return PostResult(existing, created=False)

    seq = await session.scalar(
        update(models.Room)
        .where(models.Room.id == room_id)
        .values(last_seq=models.Room.last_seq + 1)
        .returning(models.Room.last_seq)
    )
    if seq is None:
        raise RoomNotFound(room_id)
    msg = models.Message(
        id=new_id("msg"),
        room_id=room_id,
        seq=seq,
        sender_id=sender_id,
        kind=data.kind,
        reply_to=data.reply_to,
        mentions=list(data.mentions),
        body_text=data.body.text,
        body_data=None,
        idempotency_key=data.idempotency_key,
    )
    session.add(msg)
    try:
        await session.flush()
        # Delivered to listeners only when the transaction commits.
        await session.execute(
            text("SELECT pg_notify(:channel, :payload)"),
            {"channel": NOTIFY_CHANNEL, "payload": json.dumps({"room_id": room_id, "seq": seq})},
        )
        await session.commit()
    except IntegrityError:
        # A concurrent request with the same idempotency key won the race.
        await session.rollback()
        if msg in session:
            session.expunge(msg)  # never let autoflush retry the losing insert
        with session.no_autoflush:
            existing = await _find_by_key(session, sender_id, data.idempotency_key)
        if existing is None:
            raise
        if existing.room_id != room_id:
            raise ValueError("idempotency_key already used for a different room") from None
        return PostResult(existing, created=False)
    await session.refresh(msg)
    return PostResult(to_ccmp(msg, sender), created=True)
