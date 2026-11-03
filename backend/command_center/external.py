"""External agents: principals of kind 'external' that act through MCP with an access token.

Tokens are random 256-bit values, shown to the owner once and stored only as SHA-256 hashes.
An external agent can only read and post in rooms it is a member of, and only submit work
for runs that are waiting for it.
"""

from __future__ import annotations

import hashlib
import secrets
import time
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from command_center.db import models
from command_center.ids import new_id

TOKEN_PREFIX = "ccx_"  # noqa: S105 (a label, not a secret)
CACHE_SECONDS = 30.0

# Valid tokens in active use (hash -> principal id, expiry, renewed on every use). Lets a
# connected agent keep working while unknown tokens are rate limited. Issuing a new token or
# revoking clears the agent's entries, and it lives in the same process as the API, so
# revocation is immediate.
_valid: dict[str, tuple[str, float]] = {}


def cached_principal(token: str) -> str | None:
    hit = _valid.get(hash_token(token))
    if hit is None or hit[1] < time.monotonic():
        return None
    return hit[0]


def remember_principal(token: str, principal_id: str) -> None:
    if len(_valid) > 1000:
        _valid.clear()
    _valid[hash_token(token)] = (principal_id, time.monotonic() + CACHE_SECONDS)


def forget_principal(principal_id: str) -> None:
    for key in [k for k, (pid, _) in _valid.items() if pid == principal_id]:
        _valid.pop(key, None)


def new_token() -> str:
    return TOKEN_PREFIX + secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def issue_token(session: AsyncSession, principal_id: str) -> str:
    """Revoke the agent's existing tokens and issue a new one. Returns the plain token."""
    forget_principal(principal_id)
    now = datetime.now(UTC)
    await session.execute(
        update(models.AgentToken)
        .where(models.AgentToken.principal_id == principal_id, models.AgentToken.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    token = new_token()
    session.add(models.AgentToken(id=new_id("tok"), principal_id=principal_id, token_hash=hash_token(token)))
    return token


async def revoke_tokens(session: AsyncSession, principal_id: str) -> None:
    forget_principal(principal_id)
    await session.execute(
        update(models.AgentToken)
        .where(models.AgentToken.principal_id == principal_id, models.AgentToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )


async def principal_for_token(session: AsyncSession, token: str) -> models.Principal | None:
    """The active external principal for a valid, unrevoked token, or None."""
    if not token.startswith(TOKEN_PREFIX) or len(token) > 200:
        return None
    row = (
        await session.execute(
            select(models.AgentToken, models.Principal)
            .join(models.Principal, models.Principal.id == models.AgentToken.principal_id)
            .where(
                models.AgentToken.token_hash == hash_token(token),
                models.AgentToken.revoked_at.is_(None),
                models.Principal.kind == "external",
                models.Principal.status == "active",
            )
        )
    ).first()
    if row is None:
        return None
    tok, principal = row
    tok.last_used_at = datetime.now(UTC)
    return principal
