"""FastAPI application: REST API, WebSocket stream, and the static dashboard."""

import asyncio
import base64
import contextlib
import hashlib
import logging
import os
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

import uvicorn
from fastapi import Depends, FastAPI, Query, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from command_center import auth, routes_b
from command_center.config import Settings, get_settings
from command_center.db import models
from command_center.db.session import Database
from command_center.files import FileAccessError
from command_center.ids import new_id
from command_center.logging_setup import configure_logging
from command_center.mcp_gateway import build_gateway
from command_center.messaging import service
from command_center.messaging.hub import RoomHub
from command_center.orchestrator.engine import BuiltinEngine
from command_center.orchestrator.worker import RunWorker
from command_center.protocol import (
    LoginIn,
    LoginOut,
    MessageCreateIn,
    MessagePage,
    PrincipalOut,
    RoomCreateIn,
    RoomDetailOut,
    RoomOut,
)
from command_center.providers.model_port import ModelPort
from command_center.workspace import is_project_workspace, open_workspace

log = logging.getLogger(__name__)

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
MAX_SEQ = 2**63 - 1  # Postgres BIGINT


class BodySizeLimit:
    """Reject request bodies over a limit before they are buffered or parsed (413).

    Checks Content-Length up front and counts streamed bytes, so chunked bodies are capped too.
    """

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        for name, value in scope.get("headers", []):
            if name == b"content-length":
                try:
                    too_big = int(value) > self.max_bytes
                except ValueError:
                    too_big = True
                if too_big:
                    await self._reject(send)
                    return
        received = 0
        rejected = False

        async def guarded_send(message: Message) -> None:
            # After a 413 has been sent, drop whatever the app tries to send.
            if not rejected:
                await send(message)

        async def limited_receive() -> Message:
            nonlocal received, rejected
            if rejected:
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    await self._reject(send)
                    rejected = True
                    return {"type": "http.disconnect"}
            return message

        await self.app(scope, limited_receive, guarded_send)

    @staticmethod
    async def _reject(send: Send) -> None:
        body = b'{"error":{"code":"payload_too_large","message":"Request body too large"}}'
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        self.status = status
        self.code = code
        self.message = message


def error_body(code: str, message: str) -> dict[str, Any]:
    return {"error": {"code": code, "message": message}}


# ---------------------------------------------------------------- bootstrap


async def bootstrap(db: Database, settings: Settings) -> None:
    """Create the owner and the default room on first start; keep owner in every room."""
    async with db.sessionmaker() as session:
        owner = await session.scalar(select(models.Principal).where(models.Principal.kind == "owner"))
        if owner is None:
            owner = models.Principal(id=new_id("usr"), kind="owner", display_name=settings.owner_display_name)
            session.add(owner)
            await session.flush()
            log.info("created owner principal")
        elif owner.display_name != settings.owner_display_name:
            owner.display_name = settings.owner_display_name
        has_room = await session.scalar(select(models.Room.id).limit(1))
        if has_room is None:
            session.add(models.Room(id=new_id("room"), name="General", created_by=owner.id, last_seq=0))
            await session.flush()
            log.info("created default room")
        await session.execute(
            text(
                "INSERT INTO room_members (room_id, principal_id) "
                "SELECT r.id, :owner FROM rooms r ON CONFLICT DO NOTHING"
            ),
            {"owner": owner.id},
        )
        await session.commit()


# ---------------------------------------------------------------- CSP


_INLINE_SCRIPT = re.compile(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", re.S | re.I)


def build_csp(web_dist: Path, settings: Settings) -> str:
    """Strict CSP: inline scripts of the static build are allowed by hash only."""
    hashes: set[str] = set()
    if web_dist.is_dir():
        for html in web_dist.rglob("*.html"):
            for body in _INLINE_SCRIPT.findall(html.read_text(encoding="utf-8", errors="ignore")):
                if body.strip():
                    digest = base64.b64encode(hashlib.sha256(body.encode()).digest()).decode()
                    hashes.add(f"'sha256-{digest}'")
    ws_origins = sorted(
        {o.replace("http://", "ws://", 1).replace("https://", "wss://", 1) for o in settings.origins}
    )
    script_src = " ".join(["'self'", *sorted(hashes)])
    return "; ".join(
        [
            "default-src 'self'",
            f"script-src {script_src}",
            "style-src 'self' 'unsafe-inline'",
            "img-src 'self' data:",
            "font-src 'self'",
            f"connect-src 'self' {' '.join(ws_origins)}",
            "frame-ancestors 'none'",
            "base-uri 'none'",
            "form-action 'self'",
            "object-src 'none'",
        ]
    )


# ---------------------------------------------------------------- app factory


def create_app(config: Settings | None = None) -> FastAPI:
    settings: Settings = config if config is not None else get_settings()
    configure_logging(settings.log_level)
    db = Database(settings.database_url)
    hub = RoomHub(settings.asyncpg_dsn)
    limiter = auth.LoginRateLimiter(settings.login_max_failures, settings.login_window_seconds)
    csp = build_csp(settings.web_dist, settings)

    model_port = ModelPort(settings, db.sessionmaker)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        await bootstrap(db, settings)
        coordinator_id = await routes_b.seed(db, settings)
        await model_port.ensure_cap()
        settled = await model_port.settle_stale_reservations()
        if settled:
            log.warning("settled %d stale budget reservations as fully spent", settled)
        for var in ("ANTHROPIC_BASE_URL", "OPENAI_BASE_URL", "XAI_BASE_URL"):
            if os.environ.get(var):
                log.warning(
                    "%s is set: provider requests (and API keys) go to %s instead of the official API",
                    var,
                    os.environ[var],
                )
        engine = BuiltinEngine(
            db.sessionmaker,
            model_port,
            coordinator_id,
            reply_budget_usd=routes_b.DEFAULT_REPLY_BUDGET,
            simulated=settings.provider_mode == "simulated",
            max_runs_per_tree=settings.max_runs_per_tree,
            workspace=lambda: open_workspace(settings.files_root, settings.sources_root),
            attachment_max_files=settings.attachment_max_files,
            attachment_max_chars=settings.attachment_max_chars,
        )
        worker = RunWorker(
            db.sessionmaker,
            engine,
            settings.run_workers,
            lease_seconds=settings.run_lease_seconds,
            heartbeat_seconds=settings.run_heartbeat_seconds,
        )

        async def sweep_reservations() -> None:
            ticks = 0
            while True:
                await asyncio.sleep(60)
                ticks += 1
                try:
                    if ticks % 5 == 0:
                        n = await model_port.settle_stale_reservations()
                        if n:
                            log.warning("settled %d stale budget reservations as fully spent", n)
                    await engine.expire_waiting(settings.external_task_timeout_hours)
                except Exception as exc:
                    log.warning("background sweep failed (%s)", type(exc).__name__)

        sweeper = asyncio.create_task(sweep_reservations(), name="reservation-sweep")
        app.state.worker = worker
        app.state.model_port = model_port
        await hub.start()
        await worker.start()
        log.info("provider mode: %s", settings.provider_mode)
        gateway: uvicorn.Server | None = None
        gateway_task: asyncio.Task[None] | None = None
        if settings.mcp_enabled:
            gateway = uvicorn.Server(
                uvicorn.Config(
                    build_gateway(settings, db.sessionmaker, worker.wake),
                    host=settings.mcp_host,
                    port=settings.mcp_port,
                    proxy_headers=False,
                    log_level="warning",
                    lifespan="on",
                    ws="none",
                    # Bounded connections, so the gateway cannot starve the dashboard and worker.
                    limit_concurrency=64,
                    timeout_keep_alive=5,
                )
            )
            gateway_task = asyncio.create_task(gateway.serve(), name="mcp-gateway")
            log.info("MCP gateway for external agents on %s:%d/mcp", settings.mcp_host, settings.mcp_port)
        try:
            yield
        finally:
            if gateway is not None and gateway_task is not None:
                gateway.should_exit = True
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(gateway_task, 10)
            sweeper.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await sweeper
            await worker.stop()
            await hub.stop()
            await db.dispose()

    app = FastAPI(
        title="Multi-AI Command Center",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/api/docs" if settings.enable_api_docs else None,
        openapi_url="/api/openapi.json" if settings.enable_api_docs else None,
        redoc_url=None,
    )
    app.state.settings = settings
    app.state.db = db
    app.state.hub = hub

    # ------------------------------------------------------------ middleware

    class SecurityMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
            if request.url.path.startswith("/api/") and request.method not in SAFE_METHODS:
                origin = request.headers.get("origin")
                if origin is not None and origin.rstrip("/") not in settings.origins:
                    return JSONResponse(error_body("origin_not_allowed", "Origin not allowed"), 403)
                if request.headers.get("x-cc-csrf") != "1":
                    return JSONResponse(error_body("csrf_required", "Missing X-CC-CSRF header"), 403)
            response = await call_next(request)
            response.headers.setdefault("X-Content-Type-Options", "nosniff")
            response.headers.setdefault("Referrer-Policy", "no-referrer")
            response.headers.setdefault("X-Frame-Options", "DENY")
            response.headers.setdefault("Content-Security-Policy", csp)
            if request.url.path.startswith("/api/"):
                response.headers.setdefault("Cache-Control", "no-store")
            return response

    app.add_middleware(SecurityMiddleware)
    app.add_middleware(BodySizeLimit, max_bytes=settings.max_body_bytes)
    # Outermost: refuse unexpected Host headers (DNS-rebinding guard).
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)

    # Open WebSocket subscriptions per session, so logout can disconnect them immediately.
    live_streams: dict[str, set[Any]] = {}

    # ------------------------------------------------------------ errors

    @app.exception_handler(ApiError)
    async def _api_error(_request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(error_body(exc.code, exc.message), exc.status)

    @app.exception_handler(RequestValidationError)
    async def _validation(_request: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        loc = ".".join(str(p) for p in first.get("loc", []) if p != "body")
        msg = str(first.get("msg", "Invalid request")).removeprefix("Value error, ")
        return JSONResponse(error_body("validation_error", f"{loc}: {msg}" if loc else msg), 422)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, "http_error")
        return JSONResponse(error_body(code, str(exc.detail)), exc.status_code)

    # ------------------------------------------------------------ dependencies

    async def get_session() -> AsyncIterator[AsyncSession]:
        async with db.sessionmaker() as session:
            yield session

    SessionDep = Annotated[AsyncSession, Depends(get_session)]

    async def current_principal(request: Request, session: SessionDep) -> models.Principal:
        principal = await auth.principal_for_token(session, request.cookies.get(auth.SESSION_COOKIE))
        if principal is None:
            raise ApiError(401, "unauthenticated", "Sign in required")
        return principal

    PrincipalDep = Annotated[models.Principal, Depends(current_principal)]

    def principal_out(p: models.Principal) -> PrincipalOut:
        return PrincipalOut(id=p.id, kind=p.kind, display_name=p.display_name)

    async def member_room(session: AsyncSession, room_id: str, principal: models.Principal) -> models.Room:
        try:
            return await service.ensure_member(session, room_id, principal.id)
        except (service.RoomNotFound, service.NotAMember) as exc:
            # Non-members get the same answer as a missing room, so ids cannot be probed.
            raise ApiError(404, "room_not_found", "Room not found") from exc

    async def audit(
        session: AsyncSession,
        action: str,
        actor: str | None,
        target: str | None,
        request: Request | None,
        **detail: Any,
    ) -> None:
        session.add(
            models.AuditEvent(
                actor_id=actor,
                action=action,
                target=target,
                detail=detail,
                client_ip=request.client.host if request and request.client else None,
            )
        )
        await session.commit()

    # ------------------------------------------------------------ health

    @app.get("/api/health")
    async def health(session: SessionDep) -> JSONResponse:
        try:
            await session.execute(text("SELECT 1"))
        except Exception:
            return JSONResponse({"status": "degraded", "database": "unavailable"}, 503)
        return JSONResponse(
            {"status": "ok", "database": "ok", "realtime": "ok" if hub.connected else "degraded"}
        )

    # ------------------------------------------------------------ auth

    @app.post("/api/auth/login", response_model=LoginOut)
    async def login(body: LoginIn, request: Request, response: Response, session: SessionDep) -> LoginOut:
        key = request.client.host if request.client else "unknown"
        if limiter.blocked(key):
            await audit(session, "auth.login_blocked", None, None, request)
            raise ApiError(429, "rate_limited", "Too many failed attempts. Try again in a few minutes.")
        if not auth.password_matches(body.password, settings):
            limiter.record_failure(key)
            await audit(session, "auth.login_failed", None, None, request)
            raise ApiError(401, "invalid_credentials", "Incorrect password")
        limiter.reset(key)
        owner = await auth.get_owner(session)
        token = await auth.create_session(session, owner, settings.session_ttl_hours)
        response.set_cookie(
            auth.SESSION_COOKIE,
            token,
            max_age=settings.session_ttl_hours * 3600,
            httponly=True,
            samesite="strict",
            secure=settings.cookie_secure,
            path="/",
        )
        await audit(session, "auth.login", owner.id, None, request)
        return LoginOut(principal=principal_out(owner))

    @app.post("/api/auth/logout", status_code=204)
    async def logout(request: Request, session: SessionDep) -> Response:
        token = request.cookies.get(auth.SESSION_COOKIE)
        await auth.revoke_session(session, token)
        if token:
            # Wake this session's open streams; they re-check the session and close with 4401.
            for sub in list(live_streams.get(auth.hash_token(token), ())):
                sub.event.set()
        response = Response(status_code=204)
        response.delete_cookie(auth.SESSION_COOKIE, path="/")
        return response

    @app.get("/api/auth/me", response_model=PrincipalOut)
    async def me(principal: PrincipalDep) -> PrincipalOut:
        return principal_out(principal)

    # ------------------------------------------------------------ rooms

    @app.get("/api/rooms", response_model=list[RoomOut])
    async def rooms(principal: PrincipalDep, session: SessionDep) -> list[RoomOut]:
        return [
            RoomOut(
                id=r.id,
                name=r.name,
                created_at=r.created_at,
                member_count=count,
                last_seq=r.last_seq,
                project_path=r.project_path,
            )
            for r, count in await service.list_rooms(session, principal.id)
        ]

    @app.post("/api/rooms", response_model=RoomOut, status_code=201)
    async def create_room(
        body: RoomCreateIn, request: Request, principal: PrincipalDep, session: SessionDep
    ) -> RoomOut:
        project_path: str | None = None
        if body.project_path or body.new_project:
            if body.project_path and body.new_project:
                raise ApiError(422, "validation_error", "Give project_path or new_project, not both")
            ws = open_workspace(settings.files_root, settings.sources_root)
            if not is_project_workspace(ws):
                raise ApiError(422, "validation_error", "No project workspace is configured")
            assert ws is not None
            try:
                if body.new_project:
                    project = ws.create_project(
                        body.new_project.family, body.new_project.name, body.new_project.goal
                    )
                    project_path = project.path
                elif body.project_path:
                    found = ws.project(body.project_path)
                    if found is None:
                        raise ApiError(
                            422, "validation_error", "project_path: not a project in the workspace"
                        )
                    project_path = found.path
            except (FileAccessError, OSError) as exc:
                raise ApiError(422, "validation_error", f"project: {exc}") from exc
        try:
            room = await service.create_room(session, body.name, principal)
        except service.RoomExists as exc:
            raise ApiError(409, "room_exists", "A room with that name already exists") from exc
        if project_path:
            room.project_path = project_path
            await session.commit()
        await audit(
            session, "room.create", principal.id, room.id, request, name=room.name, project=project_path
        )
        return RoomOut(
            id=room.id,
            name=room.name,
            created_at=room.created_at,
            member_count=1,
            last_seq=0,
            project_path=project_path,
        )

    @app.get("/api/rooms/{room_id}", response_model=RoomDetailOut)
    async def room_detail(room_id: str, principal: PrincipalDep, session: SessionDep) -> RoomDetailOut:
        room = await member_room(session, room_id, principal)
        members = await service.room_members(session, room.id)
        return RoomDetailOut(
            id=room.id,
            name=room.name,
            created_at=room.created_at,
            member_count=len(members),
            last_seq=room.last_seq,
            project_path=room.project_path,
            members=members,
        )

    # ------------------------------------------------------------ messages

    @app.get("/api/rooms/{room_id}/messages", response_model=MessagePage)
    async def messages(
        room_id: str,
        principal: PrincipalDep,
        session: SessionDep,
        after_seq: Annotated[int, Query(ge=0, le=MAX_SEQ)] = 0,
        limit: Annotated[int, Query(ge=1, le=200)] = 100,
    ) -> MessagePage:
        await member_room(session, room_id, principal)
        items, has_more = await service.list_messages(session, room_id, after_seq, limit)
        return MessagePage(
            items=items, has_more=has_more, next_after_seq=items[-1].seq if items else after_seq
        )

    @app.post("/api/rooms/{room_id}/messages")
    async def post_message(
        room_id: str, body: MessageCreateIn, principal: PrincipalDep, session: SessionDep
    ) -> JSONResponse:
        await member_room(session, room_id, principal)
        try:
            result = await service.post_message(session, room_id, principal, body)
        except ValueError as exc:
            raise ApiError(
                409, "idempotency_conflict", "idempotency_key was already used in another room"
            ) from exc
        if result.created:
            await routes_b.route_mentions(
                app, settings, session, room_id, result.message.id, result.message.mentions, principal
            )
        return JSONResponse(jsonable_encoder(result.message), 201 if result.created else 200)

    routes_b.register(
        app,
        settings=settings,
        get_session=get_session,
        current_principal=current_principal,
        member_room=member_room,
        api_error=ApiError,
        audit=audit,
    )

    # ------------------------------------------------------------ websocket

    @app.websocket("/api/ws/rooms/{room_id}")
    async def room_stream(websocket: WebSocket, room_id: str, after_seq: int = 0) -> None:
        async def reject(code: int) -> None:
            # Accept then close, so the client receives the specific close code (a close before
            # accept becomes a bare HTTP 403). Nothing is sent before the close.
            await websocket.accept()
            await websocket.close(code=code)

        origin = websocket.headers.get("origin")
        if origin is None or origin.rstrip("/") not in settings.origins:
            await reject(4403)
            return
        if not 0 <= after_seq <= MAX_SEQ:
            await reject(4400)
            return
        token = websocket.cookies.get(auth.SESSION_COOKIE)
        async with db.sessionmaker() as session:
            principal = await auth.principal_for_token(session, token)
            if principal is None or token is None:
                await reject(4401)
                return
            try:
                await service.ensure_member(session, room_id, principal.id)
            except (service.RoomNotFound, service.NotAMember):
                await reject(4404)
                return
        await websocket.accept()
        last_sent = after_seq
        token_key = auth.hash_token(token)
        sub = hub.subscribe(room_id)  # subscribe before replay so nothing falls in the gap
        live_streams.setdefault(token_key, set()).add(sub)

        async def still_authorized() -> bool:
            # Re-checked on every wake-up: logout, expiry or removal ends the stream.
            async with db.sessionmaker() as s:
                p = await auth.principal_for_token(s, token)
                if p is None:
                    return False
                try:
                    await service.ensure_member(s, room_id, p.id)
                except (service.RoomNotFound, service.NotAMember):
                    return False
            return True

        async def flush() -> None:
            nonlocal last_sent
            while True:
                async with db.sessionmaker() as s:
                    items, has_more = await service.list_messages(s, room_id, last_sent, 200)
                for item in items:
                    await websocket.send_json({"type": "message", "message": jsonable_encoder(item)})
                    last_sent = item.seq
                if not has_more:
                    return

        async def reader() -> None:
            # Drain client frames (pongs). Binary or unexpected frames are ignored, never fatal.
            while True:
                message = await websocket.receive()
                if message["type"] == "websocket.disconnect":
                    return

        reader_task = asyncio.create_task(reader())
        try:
            await flush()
            await websocket.send_json({"type": "ready", "last_seq": last_sent})
            while not reader_task.done():
                signalled = await sub.wait(settings.ws_heartbeat_seconds)
                if reader_task.done():
                    break
                if not await still_authorized():
                    await websocket.close(code=4401)
                    break
                if not signalled:
                    await websocket.send_json({"type": "ping", "ts": datetime.now(UTC).isoformat()})
                await flush()  # on signal, and on every heartbeat as a safety net
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            sub.close()
            streams = live_streams.get(token_key)
            if streams is not None:
                streams.discard(sub)
                if not streams:
                    live_streams.pop(token_key, None)
            reader_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await reader_task

    # ------------------------------------------------------------ dashboard

    if settings.web_dist.is_dir():
        app.mount("/", StaticFiles(directory=settings.web_dist, html=True), name="web")
    else:

        @app.get("/", include_in_schema=False)
        async def no_dashboard() -> JSONResponse:
            return JSONResponse(
                {"message": "Dashboard not built. Run `npm run build` in apps/web.", "api_docs": "/api/docs"}
            )

    return app
