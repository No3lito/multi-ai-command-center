"""FastAPI application: REST API, WebSocket stream, and the static dashboard."""

import asyncio
import base64
import contextlib
import hashlib
import logging
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Query, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from command_center import auth
from command_center.config import Settings, get_settings
from command_center.db import models
from command_center.db.session import Database
from command_center.ids import new_id
from command_center.logging_setup import configure_logging
from command_center.messaging import service
from command_center.messaging.hub import RoomHub
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

log = logging.getLogger(__name__)

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


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

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        await bootstrap(db, settings)
        await hub.start()
        try:
            yield
        finally:
            await hub.stop()
            await db.dispose()

    app = FastAPI(
        title="Multi-AI Command Center",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
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
        await auth.revoke_session(session, request.cookies.get(auth.SESSION_COOKIE))
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
            RoomOut(id=r.id, name=r.name, created_at=r.created_at, member_count=count, last_seq=r.last_seq)
            for r, count in await service.list_rooms(session, principal.id)
        ]

    @app.post("/api/rooms", response_model=RoomOut, status_code=201)
    async def create_room(
        body: RoomCreateIn, request: Request, principal: PrincipalDep, session: SessionDep
    ) -> RoomOut:
        try:
            room = await service.create_room(session, body.name, principal)
        except service.RoomExists as exc:
            raise ApiError(409, "room_exists", "A room with that name already exists") from exc
        await audit(session, "room.create", principal.id, room.id, request, name=room.name)
        return RoomOut(id=room.id, name=room.name, created_at=room.created_at, member_count=1, last_seq=0)

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
            members=members,
        )

    # ------------------------------------------------------------ messages

    @app.get("/api/rooms/{room_id}/messages", response_model=MessagePage)
    async def messages(
        room_id: str,
        principal: PrincipalDep,
        session: SessionDep,
        after_seq: Annotated[int, Query(ge=0)] = 0,
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
        return JSONResponse(jsonable_encoder(result.message), 201 if result.created else 200)

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
        async with db.sessionmaker() as session:
            principal = await auth.principal_for_token(session, websocket.cookies.get(auth.SESSION_COOKIE))
            if principal is None:
                await reject(4401)
                return
            try:
                await service.ensure_member(session, room_id, principal.id)
            except (service.RoomNotFound, service.NotAMember):
                await reject(4404)
                return
        await websocket.accept()
        last_sent = max(after_seq, 0)
        sub = hub.subscribe(room_id)  # subscribe before replay so nothing falls in the gap

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
            # Drain client frames (pongs); returns when the client disconnects.
            with contextlib.suppress(WebSocketDisconnect):
                while True:
                    await websocket.receive_text()

        reader_task = asyncio.create_task(reader())
        try:
            await flush()
            await websocket.send_json({"type": "ready", "last_seq": last_sent})
            while not reader_task.done():
                signalled = await sub.wait(settings.ws_heartbeat_seconds)
                if reader_task.done():
                    break
                if not signalled:
                    await websocket.send_json({"type": "ping", "ts": datetime.now(UTC).isoformat()})
                await flush()  # on signal, and on every heartbeat as a safety net
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            sub.close()
            reader_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, WebSocketDisconnect):
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
