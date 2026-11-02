from __future__ import annotations

import asyncio
import json
import time
import uuid
from pathlib import Path
from typing import Any

import asyncpg
import httpx
import pytest
import websockets
from websockets.exceptions import ConnectionClosed

from tests.conftest import PASSWORD, Server, run_server, session_cookie
from tests.test_rooms_messages import new_room, post


async def connect(
    server: Server, room_id: str, cookie: str | None, after_seq: int = 0, origin: str | None = None
) -> websockets.ClientConnection:
    headers = {"Origin": origin or server.origin}
    if cookie:
        headers["Cookie"] = f"cc_session={cookie}"
    return await websockets.connect(
        f"{server.ws_base}/api/ws/rooms/{room_id}?after_seq={after_seq}", additional_headers=headers
    )


async def next_frame(ws: websockets.ClientConnection, kind: str, within: float = 5) -> dict[str, Any]:
    deadline = time.monotonic() + within
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(f"no {kind} frame")
        frame = json.loads(await asyncio.wait_for(ws.recv(), remaining))
        if frame["type"] == kind:
            return frame  # type: ignore[no-any-return]


async def test_replay_then_ready_then_live(server: Server, client: httpx.AsyncClient) -> None:
    room = await new_room(client)
    rid = str(room["id"])
    for i in range(3):
        await post(client, rid, f"before {i}")
    async with await connect(server, rid, session_cookie(client)) as ws:
        replayed = [(await next_frame(ws, "message"))["message"]["seq"] for _ in range(3)]
        assert replayed == [1, 2, 3]
        assert (await next_frame(ws, "ready"))["last_seq"] == 3
        started = time.monotonic()
        sent = (await post(client, rid, "live")).json()
        live = (await next_frame(ws, "message", within=2))["message"]
        assert live["id"] == sent["id"] and live["seq"] == 4
        assert time.monotonic() - started < 1.0, "live delivery should take under a second"


async def test_resume_from_after_seq_sends_only_missed(server: Server, client: httpx.AsyncClient) -> None:
    room = await new_room(client)
    rid = str(room["id"])
    for i in range(5):
        await post(client, rid, f"m{i}")
    async with await connect(server, rid, session_cookie(client), after_seq=3) as ws:
        got = [(await next_frame(ws, "message"))["message"]["seq"] for _ in range(2)]
        assert got == [4, 5]
        assert (await next_frame(ws, "ready"))["last_seq"] == 5


async def test_two_subscribers_both_receive(server: Server, client: httpx.AsyncClient) -> None:
    room = await new_room(client)
    rid = str(room["id"])
    cookie = session_cookie(client)
    async with await connect(server, rid, cookie) as a, await connect(server, rid, cookie) as b:
        await next_frame(a, "ready")
        await next_frame(b, "ready")
        sent = (await post(client, rid, "fan-out")).json()
        assert (await next_frame(a, "message"))["message"]["id"] == sent["id"]
        assert (await next_frame(b, "message"))["message"]["id"] == sent["id"]


async def test_room_isolation(server: Server, client: httpx.AsyncClient) -> None:
    a, b = await new_room(client), await new_room(client)
    async with await connect(server, str(a["id"]), session_cookie(client)) as ws:
        await next_frame(ws, "ready")
        await post(client, str(b["id"]), "other room")
        mine = (await post(client, str(a["id"]), "this room")).json()
        assert (await next_frame(ws, "message"))["message"]["id"] == mine["id"]


async def test_heartbeat_ping(server: Server, client: httpx.AsyncClient) -> None:
    room = await new_room(client)
    async with await connect(server, str(room["id"]), session_cookie(client)) as ws:
        await next_frame(ws, "ready")
        await next_frame(ws, "ping", within=4)  # test server heartbeat is 1 s
        await ws.send(json.dumps({"type": "pong"}))


@pytest.mark.parametrize(
    ("case", "code"),
    [("no_cookie", 4401), ("bad_cookie", 4401), ("bad_origin", 4403), ("missing_room", 4404)],
)
async def test_rejections_use_close_codes(
    server: Server, client: httpx.AsyncClient, case: str, code: int
) -> None:
    room = await new_room(client)
    rid, cookie, origin = str(room["id"]), session_cookie(client), None
    if case == "no_cookie":
        cookie = ""
    elif case == "bad_cookie":
        cookie = "forged-token"
    elif case == "bad_origin":
        origin = "https://evil.example"
    elif case == "missing_room":
        rid = "room_" + "f" * 32
    async with await connect(server, rid, cookie or None, origin=origin) as ws:
        with pytest.raises(ConnectionClosed) as info:
            await asyncio.wait_for(ws.recv(), 5)
        assert info.value.rcvd is not None and info.value.rcvd.code == code


async def test_delivery_survives_listener_connection_loss(
    server: Server, client: httpx.AsyncClient, database_url: str
) -> None:
    """Kill the server's LISTEN connection; messages must still arrive (reconnect or heartbeat re-check)."""
    room = await new_room(client)
    rid = str(room["id"])
    async with await connect(server, rid, session_cookie(client)) as ws:
        await next_frame(ws, "ready")
        conn = await asyncpg.connect(database_url)
        try:
            killed = await conn.fetchval(
                "SELECT count(pg_terminate_backend(pid)) FROM pg_stat_activity "
                "WHERE query LIKE 'LISTEN%' AND pid <> pg_backend_pid()"
            )
        finally:
            await conn.close()
        assert killed >= 1
        sent = (await post(client, rid, "after listener loss")).json()
        assert (await next_frame(ws, "message", within=5))["message"]["id"] == sent["id"]


async def test_messages_persist_across_server_restart(database_url: str, tmp_path: Path) -> None:
    text = f"durable {uuid.uuid4().hex}"
    with run_server(database_url, tmp_path) as srv:
        async with httpx.AsyncClient(base_url=srv.base_url, headers={"X-CC-CSRF": "1"}) as c:
            await c.post("/api/auth/login", json={"password": PASSWORD})
            room = await new_room(c, "Durable")
            await post(c, str(room["id"]), text)
    with run_server(database_url, tmp_path) as srv2:
        async with httpx.AsyncClient(base_url=srv2.base_url, headers={"X-CC-CSRF": "1"}) as c:
            await c.post("/api/auth/login", json={"password": PASSWORD})
            items = (await c.get(f"/api/rooms/{room['id']}/messages")).json()["items"]
            assert [m["body"]["text"] for m in items] == [text]
