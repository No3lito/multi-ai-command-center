from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path

import httpx
import jsonschema

SCHEMA = json.loads(
    (Path(__file__).resolve().parents[2] / "packages" / "protocol" / "ccmp.schema.json").read_text()
)
validator = jsonschema.Draft202012Validator(SCHEMA, format_checker=jsonschema.FormatChecker())


def key() -> str:
    return uuid.uuid4().hex


async def new_room(c: httpx.AsyncClient, prefix: str = "room") -> dict[str, object]:
    r = await c.post("/api/rooms", json={"name": f"{prefix} {uuid.uuid4().hex[:8]}"})
    assert r.status_code == 201, r.text
    return r.json()  # type: ignore[no-any-return]


async def post(c: httpx.AsyncClient, room_id: str, text: str, k: str | None = None) -> httpx.Response:
    return await c.post(
        f"/api/rooms/{room_id}/messages",
        json={"kind": "chat", "body": {"text": text}, "idempotency_key": k or key()},
    )


async def test_default_room_exists(client: httpx.AsyncClient) -> None:
    names = [r["name"] for r in (await client.get("/api/rooms")).json()]
    assert "General" in names


async def test_create_room_and_detail(client: httpx.AsyncClient) -> None:
    room = await new_room(client, "Design")
    assert room["member_count"] == 1 and room["last_seq"] == 0
    detail = (await client.get(f"/api/rooms/{room['id']}")).json()
    assert [m["kind"] for m in detail["members"]] == ["owner"]


async def test_duplicate_room_name_case_insensitive(client: httpx.AsyncClient) -> None:
    room = await new_room(client, "Dup")
    r = await client.post("/api/rooms", json={"name": str(room["name"]).upper()})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "room_exists"


async def test_room_name_validation(client: httpx.AsyncClient) -> None:
    for bad in ("", "   ", "x" * 81):
        r = await client.post("/api/rooms", json={"name": bad})
        assert r.status_code == 422, bad
        assert r.json()["error"]["code"] == "validation_error"


async def test_unknown_room_is_404(client: httpx.AsyncClient) -> None:
    fake = "room_" + "0" * 32
    assert (await client.get(f"/api/rooms/{fake}")).status_code == 404
    assert (await post(client, fake, "hi")).status_code == 404


async def test_message_is_valid_ccmp_and_persisted(client: httpx.AsyncClient) -> None:
    room = await new_room(client)
    r = await post(client, str(room["id"]), "  Hello <b>agents</b>\nline two  ")
    assert r.status_code == 201
    msg = r.json()
    validator.validate(msg)
    assert msg["seq"] == 1 and msg["sender"]["kind"] == "owner"
    assert msg["body"]["text"] == "Hello <b>agents</b>\nline two"  # stored verbatim, trimmed only
    page = (await client.get(f"/api/rooms/{room['id']}/messages")).json()
    assert [m["id"] for m in page["items"]] == [msg["id"]]
    for m in page["items"]:
        validator.validate(m)


async def test_idempotent_retry_returns_original(client: httpx.AsyncClient) -> None:
    room = await new_room(client)
    k = key()
    first = await post(client, str(room["id"]), "once", k)
    second = await post(client, str(room["id"]), "once", k)
    assert first.status_code == 201 and second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    page = (await client.get(f"/api/rooms/{room['id']}/messages")).json()
    assert len(page["items"]) == 1


async def test_concurrent_duplicate_submissions_create_one_message(client: httpx.AsyncClient) -> None:
    room = await new_room(client)
    k = key()
    results = await asyncio.gather(*[post(client, str(room["id"]), "race", k) for _ in range(10)])
    assert sorted(r.status_code for r in results).count(201) == 1
    assert len({r.json()["id"] for r in results}) == 1


async def test_idempotency_key_reuse_in_other_room_conflicts(client: httpx.AsyncClient) -> None:
    a, b = await new_room(client), await new_room(client)
    k = key()
    assert (await post(client, str(a["id"]), "a", k)).status_code == 201
    r = await post(client, str(b["id"]), "b", k)
    assert r.status_code == 409 and r.json()["error"]["code"] == "idempotency_conflict"


async def test_seq_is_gap_free_under_concurrency(client: httpx.AsyncClient) -> None:
    room = await new_room(client)
    results = await asyncio.gather(*[post(client, str(room["id"]), f"m{i}") for i in range(40)])
    assert all(r.status_code == 201 for r in results)
    seqs = sorted(r.json()["seq"] for r in results)
    assert seqs == list(range(1, 41))
    rooms = {r["id"]: r for r in (await client.get("/api/rooms")).json()}
    assert rooms[room["id"]]["last_seq"] == 40


async def test_rooms_have_independent_sequences(client: httpx.AsyncClient) -> None:
    a, b = await new_room(client), await new_room(client)
    await asyncio.gather(
        *[post(client, str(a["id"]), "a") for _ in range(5)],
        *[post(client, str(b["id"]), "b") for _ in range(3)],
    )
    for room, n in ((a, 5), (b, 3)):
        items = (await client.get(f"/api/rooms/{room['id']}/messages")).json()["items"]
        assert [m["seq"] for m in items] == list(range(1, n + 1))


async def test_pagination(client: httpx.AsyncClient) -> None:
    room = await new_room(client)
    for i in range(5):
        await post(client, str(room["id"]), f"m{i}")
    p1 = (await client.get(f"/api/rooms/{room['id']}/messages", params={"limit": 2})).json()
    assert [m["seq"] for m in p1["items"]] == [1, 2] and p1["has_more"] and p1["next_after_seq"] == 2
    p3 = (await client.get(f"/api/rooms/{room['id']}/messages", params={"after_seq": 4, "limit": 2})).json()
    assert [m["seq"] for m in p3["items"]] == [5] and not p3["has_more"]


async def test_message_validation(client: httpx.AsyncClient) -> None:
    room = await new_room(client)
    rid = room["id"]
    cases = [
        {"kind": "chat", "body": {"text": "   "}, "idempotency_key": key()},
        {"kind": "chat", "body": {"text": "x" * 32001}, "idempotency_key": key()},
        {"kind": "chat", "body": {"text": "ok"}, "idempotency_key": "short"},
        {"kind": "approval.decision", "body": {"text": "approve"}, "idempotency_key": key()},
        {"kind": "chat", "body": {"text": "ok"}, "idempotency_key": key(), "sender": "agt_x"},
    ]
    for body in cases:
        r = await client.post(f"/api/rooms/{rid}/messages", json=body)
        assert r.status_code == 422, body
