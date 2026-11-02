"""Owner authentication: password login, server-side sessions, login rate limiting."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from command_center.config import Settings
from command_center.db import models
from command_center.ids import new_id

SESSION_COOKIE = "cc_session"


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def password_matches(candidate: str, settings: Settings) -> bool:
    expected = hashlib.sha256(settings.owner_password.get_secret_value().encode()).digest()
    given = hashlib.sha256(candidate.encode()).digest()
    return hmac.compare_digest(expected, given)


class LoginRateLimiter:
    """Failed-attempt limiter per client key. In-process; the API runs as one process in Milestone A."""

    def __init__(self, max_failures: int, window_seconds: int) -> None:
        self.max_failures = max_failures
        self.window = window_seconds
        self._failures: dict[str, deque[float]] = defaultdict(deque)

    def _prune(self, key: str, now: float) -> deque[float]:
        q = self._failures[key]
        while q and now - q[0] > self.window:
            q.popleft()
        return q

    def blocked(self, key: str) -> bool:
        return len(self._prune(key, time.monotonic())) >= self.max_failures

    def record_failure(self, key: str) -> None:
        now = time.monotonic()
        self._prune(key, now).append(now)

    def reset(self, key: str) -> None:
        self._failures.pop(key, None)


async def get_owner(session: AsyncSession) -> models.Principal:
    owner = await session.scalar(select(models.Principal).where(models.Principal.kind == "owner"))
    if owner is None:
        raise RuntimeError("owner principal missing; run bootstrap")
    return owner


async def create_session(session: AsyncSession, principal: models.Principal, ttl_hours: int) -> str:
    token = secrets.token_urlsafe(32)
    session.add(
        models.Session(
            id=new_id("ses"),
            principal_id=principal.id,
            token_hash=hash_token(token),
            expires_at=datetime.now(UTC) + timedelta(hours=ttl_hours),
        )
    )
    await session.commit()
    return token


async def principal_for_token(session: AsyncSession, token: str | None) -> models.Principal | None:
    if not token or len(token) > 200:
        return None
    stmt = (
        select(models.Principal)
        .join(models.Session, models.Session.principal_id == models.Principal.id)
        .where(
            models.Session.token_hash == hash_token(token),
            models.Session.revoked_at.is_(None),
            models.Session.expires_at > datetime.now(UTC),
            models.Principal.status == "active",
        )
    )
    return await session.scalar(stmt)


async def revoke_session(session: AsyncSession, token: str | None) -> None:
    if not token:
        return
    await session.execute(
        update(models.Session)
        .where(models.Session.token_hash == hash_token(token), models.Session.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )
    await session.commit()
