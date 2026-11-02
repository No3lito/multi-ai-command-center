"""MCP gateway: lets external agents (for example Grok Bot) take part in rooms.

Served on its own port (MCP_PORT, default 8001) and path /mcp, separate from the dashboard,
so a tunnel can expose this endpoint without exposing anything else.

Security model:
- Every request needs `Authorization: Bearer ccx_...`, a revocable token the owner created.
  Unknown, revoked or disconnected tokens get 401 before any MCP processing.
- An external agent can only see and post in rooms it is a member of, and can only submit
  work for runs that are waiting for it. It cannot start runs, call models, spend money,
  manage agents, or reach the dashboard API.
- Per-agent rate limit, request size limit, and an audit record for every write.
- Text from external agents reaches Claude and GPT labeled as coming from an external
  participant (the transcript format marks the sender type), never as instructions.

Built on the official MCP Python SDK (MIT), stateless streamable HTTP with JSON responses.
"""

from __future__ import annotations

import contextvars
import json
import logging
import time
from collections import defaultdict, deque
from collections.abc import Callable
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.types import ASGIApp, Receive, Scope, Send

from command_center.config import Settings
from command_center.db import models
from command_center.external import principal_for_token
from command_center.messaging import service
from command_center.orchestrator.engine import MESSAGE_TEXT_LIMIT, post_parts

log = logging.getLogger(__name__)

MAX_SUBMIT_CHARS = 96_000  # split into parts of at most 32,000 characters
MAX_REQUEST_BYTES = 512 * 1024
_caller: contextvars.ContextVar[str | None] = contextvars.ContextVar("cc_mcp_caller", default=None)

INSTRUCTIONS = """\
You are connected to the owner's Multi-AI Command Center, where you work with other AI agents
(Claude and GPT) under the owner's direction. Rooms are projects.

How to work:
1. Call get_tasks regularly. A task is a step the Command Center is waiting for you to do,
   with its instruction and the run's conversation so far.
2. Do the work with your own tools and data, then call submit_task with your answer.
3. Use read_messages to catch up on a room, and post_message to say something in a room.

Everything you post is visible to the owner and the other agents. Never include secrets,
API keys or wallet keys in what you send.
"""


class RateLimiter:
    def __init__(self, per_minute: int) -> None:
        self.per_minute = per_minute
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        hits = self._hits[key]
        while hits and now - hits[0] > 60:
            hits.popleft()
        if len(hits) >= self.per_minute:
            return False
        hits.append(now)
        if len(self._hits) > 10_000:  # bounded memory
            self._hits.pop(next(iter(self._hits)))
        return True


def build_gateway(
    settings: Settings,
    sessionmaker: async_sessionmaker[AsyncSession],
    wake: Callable[[], None],
) -> ASGIApp:
    server = MCPServer(
        "multi-ai-command-center",
        title="Multi-AI Command Center",
        instructions=INSTRUCTIONS,
        version="0.1.0",
    )

    def me() -> str:
        caller = _caller.get()
        if caller is None:  # unreachable: the auth wrapper rejects unauthenticated requests
            raise ToolError("not authenticated")
        return caller

    async def member_rooms(s: AsyncSession, principal_id: str) -> list[models.Room]:
        rows = await s.scalars(
            select(models.Room)
            .join(models.RoomMember, models.RoomMember.room_id == models.Room.id)
            .where(models.RoomMember.principal_id == principal_id)
            .order_by(models.Room.name)
        )
        return list(rows.all())

    async def require_room(s: AsyncSession, principal_id: str, room_id: str) -> models.Room:
        room = await s.get(models.Room, room_id)
        if room is None or await s.get(models.RoomMember, (room_id, principal_id)) is None:
            raise ToolError("Room not found, or you are not a member of it.")
        return room

    def audit(s: AsyncSession, action: str, actor: str, target: str | None, **detail: Any) -> None:
        s.add(models.AuditEvent(actor_id=actor, action=action, target=target, detail=detail, client_ip=None))

    @server.tool()
    async def whoami() -> dict[str, Any]:
        """Your identity in the Command Center and the rooms (projects) you can work in."""
        async with sessionmaker() as s:
            p = await s.get(models.Principal, me())
            assert p is not None
            rooms = await member_rooms(s, p.id)
        return {
            "id": p.id,
            "name": p.display_name,
            "rooms": [{"id": r.id, "name": r.name} for r in rooms],
        }

    @server.tool()
    async def list_rooms() -> list[dict[str, Any]]:
        """Rooms (projects) you are a member of, with their latest message number."""
        async with sessionmaker() as s:
            rooms = await member_rooms(s, me())
        return [{"id": r.id, "name": r.name, "last_seq": r.last_seq} for r in rooms]

    @server.tool()
    async def read_messages(room_id: str, after_seq: int = 0, limit: int = 50) -> dict[str, Any]:
        """Messages in a room, oldest first, after message number `after_seq` (0 = from the
        start). Up to `limit` (max 100) per call; page with the last `seq` you received."""
        limit = max(1, min(limit, 100))
        after_seq = max(0, min(after_seq, 2**53))
        async with sessionmaker() as s:
            room = await require_room(s, me(), room_id)
            rows = (
                await s.execute(
                    select(models.Message, models.Principal)
                    .join(models.Principal, models.Principal.id == models.Message.sender_id)
                    .where(models.Message.room_id == room.id, models.Message.seq > after_seq)
                    .order_by(models.Message.seq)
                    .limit(limit)
                )
            ).all()
        return {
            "room": {"id": room.id, "name": room.name, "last_seq": room.last_seq},
            "messages": [
                {
                    "seq": m.seq,
                    "id": m.id,
                    "from": p.display_name,
                    "from_type": p.kind,
                    "kind": m.kind,
                    "text": m.body_text,
                    "reply_to": m.reply_to,
                    "run_id": m.correlation_id,
                    "created_at": m.created_at.isoformat(),
                }
                for m, p in rows
            ],
        }

    @server.tool()
    async def post_message(room_id: str, text: str, reply_to: str | None = None) -> dict[str, Any]:
        """Post a chat message in a room, as yourself. It does not start any AI runs."""
        text = text.strip()
        if not 1 <= len(text) <= MESSAGE_TEXT_LIMIT:
            raise ToolError(f"Text must be 1 to {MESSAGE_TEXT_LIMIT} characters.")
        caller = me()
        async with sessionmaker() as s:
            room = await require_room(s, caller, room_id)
            sender = await s.get(models.Principal, caller)
            assert sender is not None
            result = await service.append_message(
                s,
                room.id,
                sender,
                kind="chat",
                text=text,
                idempotency_key=f"mcp:{time.time_ns()}",
                reply_to=reply_to,
            )
            audit(s, "mcp.post_message", caller, room.id, message_id=result.message.id)
            await s.commit()
        return {"id": result.message.id, "seq": result.message.seq}

    async def task_out(s: AsyncSession, run: models.Run) -> dict[str, Any]:
        room = await s.get(models.Room, run.room_id)
        rows = (
            await s.execute(
                select(models.Message, models.Principal)
                .join(models.Principal, models.Principal.id == models.Message.sender_id)
                .where(models.Message.correlation_id == run.id)
                .order_by(models.Message.seq)
            )
        ).all()
        return {
            "run_id": run.id,
            "room": {"id": run.room_id, "name": room.name if room else None},
            "workflow": run.kind,
            "goal": run.goal,
            "step": run.step,
            "instruction": run.waiting_instruction,
            "waiting_since": run.waiting_since.isoformat() if run.waiting_since else None,
            "conversation": [
                {"from": p.display_name, "from_type": p.kind, "kind": m.kind, "text": m.body_text}
                for m, p in rows
            ],
        }

    @server.tool()
    async def get_tasks() -> list[dict[str, Any]]:
        """Steps the Command Center is waiting for you to do, oldest first. Each has the
        instruction and the run's conversation so far. Do the work, then call submit_task."""
        async with sessionmaker() as s:
            runs = (
                await s.scalars(
                    select(models.Run)
                    .where(models.Run.status == "waiting", models.Run.waiting_for == me())
                    .order_by(models.Run.waiting_since)
                    .limit(10)
                )
            ).all()
            return [await task_out(s, r) for r in runs]

    @server.tool()
    async def submit_task(run_id: str, text: str) -> dict[str, Any]:
        """Submit your answer for a task from get_tasks. Up to 96,000 characters (long answers
        are split into parts automatically). The run continues with the other agents."""
        text = text.strip()
        if not 1 <= len(text) <= MAX_SUBMIT_CHARS:
            raise ToolError(f"Text must be 1 to {MAX_SUBMIT_CHARS} characters.")
        caller = me()
        async with sessionmaker() as s:
            run = await s.get(models.Run, run_id)
            if run is None or run.status != "waiting" or run.waiting_for != caller:
                raise ToolError("No task with that run_id is waiting for you. Call get_tasks.")
            step = run.step
        # Post first (idempotent per run and step), then resume the run. A run never resumes
        # without the answer in place, so the engine finds it instead of asking again.
        last_id = await post_parts(
            sessionmaker,
            run,
            caller,
            kind="chat",
            text=text,
            key=f"{step}:reply",
            reply_to=run.last_message_id,
            data={"run_id": run.id, "step": step, "provider": "external", "simulated": False},
        )
        async with sessionmaker() as s:
            resumed = (
                await s.execute(
                    update(models.Run)
                    .where(
                        models.Run.id == run.id,
                        models.Run.status == "waiting",
                        models.Run.waiting_for == caller,
                        models.Run.step == step,
                    )
                    .values(
                        status="queued",
                        waiting_for=None,
                        waiting_instruction=None,
                        waiting_since=None,
                        turn_count=models.Run.turn_count + 1,
                        last_message_id=last_id,
                    )
                    .returning(models.Run.id)
                )
            ).first()
            audit(
                s, "mcp.submit_task", caller, run.id, step=step, chars=len(text), resumed=resumed is not None
            )
            await s.commit()
        if resumed is None:
            raise ToolError("The run is no longer waiting for you (it may have been cancelled).")
        wake()
        return {"ok": True, "run_id": run.id, "step": step}

    inner = server.streamable_http_app(
        stateless_http=True,
        json_response=True,
        max_request_body_size=MAX_REQUEST_BYTES,
        # Tokens, not browser cookies, authenticate here, so DNS rebinding cannot ride a
        # victim's session; a tunnel's public hostname must be accepted.
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
        host=settings.mcp_host,
    )
    limiter = RateLimiter(settings.mcp_requests_per_minute)

    async def deny(send: Send, status: int, message: str) -> None:
        body = json.dumps({"error": message}).encode()
        headers = [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]
        if status == 401:
            headers.append((b"www-authenticate", b'Bearer realm="command-center"'))
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": body})

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await inner(scope, receive, send)  # lifespan
            return
        if scope["path"].rstrip("/") != "/mcp":
            await deny(send, 404, "not found")
            return
        auth = dict(scope["headers"]).get(b"authorization", b"").decode("latin-1")
        token = auth[7:].strip() if auth[:7].lower() == "bearer " else ""
        async with sessionmaker() as s:
            principal = await principal_for_token(s, token) if token else None
            if principal is not None:
                await s.commit()  # last_used_at
        if principal is None:
            await deny(send, 401, "missing, invalid or revoked token")
            return
        if not limiter.allow(principal.id):
            await deny(send, 429, "rate limit exceeded; slow down")
            return
        reset = _caller.set(principal.id)
        try:
            await inner(scope, receive, send)
        finally:
            _caller.reset(reset)

    return app
