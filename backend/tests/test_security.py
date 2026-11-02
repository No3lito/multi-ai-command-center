"""Regression tests for the Milestone A security review findings."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import re
import time
import uuid
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from websockets.exceptions import ConnectionClosed

from command_center.auth import LoginRateLimiter
from command_center.config import Settings
from tests.conftest import PASSWORD, Server, run_server, session_cookie
from tests.test_realtime import connect, next_frame
from tests.test_rooms_messages import new_room, post

REPO = Path(__file__).resolve().parents[2]


async def closed_with(ws: object, code: int, within: float = 5) -> None:
    with pytest.raises(ConnectionClosed) as info:
        deadline = time.monotonic() + within
        while time.monotonic() < deadline:
            await asyncio.wait_for(ws.recv(), deadline - time.monotonic())  # type: ignore[attr-defined]
    assert info.value.rcvd is not None and info.value.rcvd.code == code


# Finding 1: streams must end when the session ends.
async def test_logout_closes_open_streams_immediately(server: Server) -> None:
    async with httpx.AsyncClient(base_url=server.base_url, headers={"X-CC-CSRF": "1"}) as c:
        await c.post("/api/auth/login", json={"password": PASSWORD})
        room = await new_room(c)
        async with await connect(server, str(room["id"]), session_cookie(c)) as ws:
            await next_frame(ws, "ready")
            started = time.monotonic()
            assert (await c.post("/api/auth/logout")).status_code == 204
            await closed_with(ws, 4401, within=3)
            assert time.monotonic() - started < 3


async def test_revoked_session_stops_stream_on_next_heartbeat(server: Server, database_url: str) -> None:
    import asyncpg

    async with httpx.AsyncClient(base_url=server.base_url, headers={"X-CC-CSRF": "1"}) as c:
        await c.post("/api/auth/login", json={"password": PASSWORD})
        room = await new_room(c)
        async with await connect(server, str(room["id"]), session_cookie(c)) as ws:
            await next_frame(ws, "ready")
            # Expire every session behind the server's back (as if 12 hours passed).
            conn = await asyncpg.connect(database_url)
            try:
                await conn.execute("UPDATE sessions SET expires_at = now() - interval '1 second'")
            finally:
                await conn.close()
            await closed_with(ws, 4401, within=4)  # test heartbeat is 1 s


# Finding 4: bounded payloads.
async def test_oversized_body_rejected_before_parsing(anon: httpx.AsyncClient) -> None:
    big = b'{"password": "' + b"x" * (256 * 1024) + b'"}'
    r = await anon.post("/api/auth/login", content=big, headers={"Content-Type": "application/json"})
    assert r.status_code == 413
    assert r.json()["error"]["code"] == "payload_too_large"


async def test_oversized_chunked_body_rejected(anon: httpx.AsyncClient) -> None:
    async def chunks():  # type: ignore[no-untyped-def]
        for _ in range(64):
            yield b"x" * 8192

    r = await anon.post(
        "/api/auth/login", content=chunks(), headers={"Content-Type": "application/json", "X-CC-CSRF": "1"}
    )
    assert r.status_code == 413


async def test_mentions_must_be_principal_ids(client: httpx.AsyncClient) -> None:
    room = await new_room(client)
    for mentions in (["x" * 2_000_000], ["@noel"], ["usr_" + "0" * 31]):
        r = await client.post(
            f"/api/rooms/{room['id']}/messages",
            json={
                "kind": "chat",
                "body": {"text": "hi"},
                "idempotency_key": uuid.uuid4().hex,
                "mentions": mentions,
            },
        )
        assert r.status_code in (413, 422), mentions
    ok = await client.post(
        f"/api/rooms/{room['id']}/messages",
        json={
            "kind": "chat",
            "body": {"text": "hi"},
            "idempotency_key": uuid.uuid4().hex,
            "mentions": ["usr_" + "a" * 32],
        },
    )
    assert ok.status_code == 201


# Finding 5: X-Forwarded-For must not reset the login limiter.
async def test_forwarded_for_spoofing_does_not_bypass_rate_limit(database_url: str, tmp_path: Path) -> None:
    with run_server(database_url, tmp_path, LOGIN_MAX_FAILURES="3", LOGIN_WINDOW_SECONDS="60") as srv:
        async with httpx.AsyncClient(base_url=srv.base_url, headers={"X-CC-CSRF": "1"}) as c:
            for i in range(3):
                await c.post(
                    "/api/auth/login",
                    json={"password": "nope-nope-nope"},
                    headers={"X-Forwarded-For": f"10.0.0.{i}"},
                )
            r = await c.post(
                "/api/auth/login", json={"password": PASSWORD}, headers={"X-Forwarded-For": "10.9.9.9"}
            )
            assert r.status_code == 429


# Finding 7: range checks instead of 500s.
async def test_after_seq_out_of_range(server: Server, client: httpx.AsyncClient) -> None:
    room = await new_room(client)
    r = await client.get(f"/api/rooms/{room['id']}/messages", params={"after_seq": 10**20})
    assert r.status_code == 422
    async with await connect(server, str(room["id"]), session_cookie(client), after_seq=2**63) as ws:
        await closed_with(ws, 4400)


# Finding 8: secrets never echoed in config errors.
def test_short_password_not_echoed_in_error() -> None:
    with pytest.raises(ValidationError) as info:
        Settings(database_url="postgresql://x/y", owner_password="shortsecret")  # type: ignore[arg-type]
    assert "shortsecret" not in str(info.value)


# Finding 9: concurrent reuse of a key across rooms never returns another room's message.
async def test_cross_room_idempotency_race(client: httpx.AsyncClient) -> None:
    rooms = [await new_room(client) for _ in range(4)]
    key = uuid.uuid4().hex
    results = await asyncio.gather(
        *[post(client, str(r["id"]), "race", key) for r in rooms for _ in range(3)]
    )
    created = [r for r in results if r.status_code == 201]
    assert len(created) == 1
    winner_room = created[0].json()["room_id"]
    for r in results:
        assert r.status_code in (200, 201, 409)
        if r.status_code == 200:
            assert r.json()["room_id"] == winner_room


# Finding 10: binary frames are ignored, the stream keeps working.
async def test_binary_frame_does_not_break_stream(server: Server, client: httpx.AsyncClient) -> None:
    room = await new_room(client)
    async with await connect(server, str(room["id"]), session_cookie(client)) as ws:
        await next_frame(ws, "ready")
        log_offset = len(server.logs())
        await ws.send(b"\x00\x01binary")
        sent = (await post(client, str(room["id"]), "still alive")).json()
        assert (await next_frame(ws, "message"))["message"]["id"] == sent["id"]
    await asyncio.sleep(0.2)
    assert "Traceback" not in server.logs()[log_offset:]


# Extras from the review's "later" list that were cheap to close now.
async def test_unexpected_host_header_rejected(server: Server) -> None:
    async with httpx.AsyncClient(base_url=server.base_url) as c:
        r = await c.get("/api/health", headers={"Host": "attacker.example"})
        assert r.status_code == 400


async def test_api_docs_disabled_by_default(anon: httpx.AsyncClient) -> None:
    assert (await anon.get("/api/docs")).status_code == 404
    assert (await anon.get("/api/openapi.json")).status_code == 404


def test_rate_limiter_drops_expired_entries() -> None:
    limiter = LoginRateLimiter(max_failures=2, window_seconds=0)
    for i in range(100):
        limiter.record_failure(f"client-{i}")
    time.sleep(0.01)
    for i in range(100):
        assert not limiter.blocked(f"client-{i}")
    assert limiter._failures == {}


def test_csp_hashes_every_inline_script_of_the_build() -> None:
    from command_center.app import build_csp

    out = REPO / "apps" / "web" / "out"
    if not (out / "index.html").exists():
        pytest.skip("dashboard not built")
    settings = Settings(database_url="postgresql://x/y", owner_password="long-enough-password", web_dist=out)  # type: ignore[arg-type]
    csp = build_csp(out, settings)
    pattern = re.compile(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", re.S | re.I)
    scripts = [s for s in pattern.findall((out / "index.html").read_text()) if s.strip()]
    assert scripts, "expected inline scripts in the static build"
    for body in scripts:
        digest = base64.b64encode(hashlib.sha256(body.encode()).digest()).decode()
        assert f"'sha256-{digest}'" in csp
