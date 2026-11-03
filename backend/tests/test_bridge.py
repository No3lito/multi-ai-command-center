"""Grok Bot bridge: external agents over MCP.

The MCP side uses the official MCP Python SDK client against the real server process, the
same way Grok Bot connects. Model calls go to the FAKE provider server (no real API, no
cost). Proves the protocol, auth, scoping and orchestration, not Grok Bot itself.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import httpx2
import pytest
from mcp.client.client import Client
from mcp.client.streamable_http import streamable_http_client
from sqlalchemy import select

from command_center.db import models
from command_center.orchestrator.engine import BuiltinEngine, split_text
from command_center.providers.model_port import ModelPort
from tests.conftest import Server, run_fake_providers, run_server
from tests.test_coordinator import fake_calls, general_and_agents, logged_in, run_messages
from tests.test_review_fixes import Adapter, add_run, cfg, world  # noqa: F401  (fixture)

LIVE = {"ANTHROPIC_API_KEY": "sk-ant-fake", "OPENAI_API_KEY": "sk-openai-fake", "LIVE_BUDGET_USD": "2.00"}


@asynccontextmanager
async def mcp(srv: Server, token: str) -> AsyncIterator[Client]:
    async with httpx2.AsyncClient(headers={"Authorization": f"Bearer {token}"}, timeout=30) as hc:
        async with Client(streamable_http_client(srv.mcp_url, http_client=hc)) as client:
            yield client


async def call(client: Client, tool: str, **args: Any) -> Any:
    result = await client.call_tool(tool, args)
    if result.is_error:
        raise RuntimeError(result.content[0].text)  # type: ignore[union-attr]
    if result.structured_content is not None:
        data = result.structured_content
        return data.get("result", data) if isinstance(data, dict) and set(data) == {"result"} else data
    return json.loads(result.content[0].text)  # type: ignore[union-attr]


async def connect(c: httpx.AsyncClient, name: str = "Grok Bot", **body: Any) -> dict[str, Any]:
    if "room_ids" not in body:
        rooms = (await c.get("/api/rooms")).json()
        body["room_ids"] = [next(r["id"] for r in rooms if r["name"] == "General")]
    r = await c.post("/api/connections", json={"display_name": name, **body})
    assert r.status_code == 201, r.text
    return r.json()  # type: ignore[no-any-return]


async def raw_post(srv: Server, token: str | None) -> int:
    headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    async with httpx.AsyncClient() as h:
        return (await h.post(srv.mcp_url, json=body, headers=headers)).status_code


async def wait_status(
    c: httpx.AsyncClient, run_id: str, statuses: set[str], within: float = 30
) -> dict[str, Any]:
    deadline = time.monotonic() + within
    run: dict[str, Any] = {}
    while time.monotonic() < deadline:
        run = (await c.get(f"/api/runs/{run_id}")).json()
        if run["status"] in statuses:
            return run
        await asyncio.sleep(0.2)
    raise TimeoutError(f"run {run_id} is {run.get('status')}, wanted {statuses}")


@pytest.fixture
def sim_srv(fresh_database_url: str, tmp_path: Path):  # type: ignore[no-untyped-def]
    with run_server(
        fresh_database_url, tmp_path, PROVIDER_MODE="simulated", MCP_REQUESTS_PER_MINUTE="40"
    ) as srv:
        yield srv


async def test_tokens_rooms_and_revocation(sim_srv: Server) -> None:
    async with logged_in(sim_srv) as c:
        assert await raw_post(sim_srv, None) == 401
        assert await raw_post(sim_srv, "ccx_not-a-real-token") == 401
        conn = await connect(c)
        token = conn["token"]
        assert token.startswith("ccx_") and len(token) > 40
        assert [r["name"] for r in conn["rooms"]] == ["General"]
        listed = (await c.get("/api/connections")).json()
        assert [x["display_name"] for x in listed] == ["Grok Bot"] and listed[0]["token"] is None
        assert (
            await c.post(
                "/api/connections",
                json={
                    "display_name": "grok bot",
                    "room_ids": conn["rooms"][0:1] and [conn["rooms"][0]["id"]],
                },
            )
        ).status_code == 409
        no_room = await c.post("/api/connections", json={"display_name": "Other"})
        assert no_room.status_code == 422 and "pick at least one room" in no_room.text
        secret = (await c.post("/api/rooms", json={"name": "Private"})).json()

        async with mcp(sim_srv, token) as client:
            tools = {t.name for t in (await client.list_tools()).tools}
            assert tools == {
                "whoami",
                "list_rooms",
                "read_messages",
                "post_message",
                "get_tasks",
                "get_decisions",
                "submit_task",
            }
            me = await call(client, "whoami")
            assert me["name"] == "Grok Bot" and [r["name"] for r in me["rooms"]] == ["General"]
            general = me["rooms"][0]["id"]
            assert await call(client, "get_decisions", room_id=general) == []
            posted = await call(client, "post_message", room_id=general, text="Hello from Grok Bot")
            read = await call(client, "read_messages", room_id=general, after_seq=0)
            mine = [m for m in read["messages"] if m["id"] == posted["id"]]
            assert mine and mine[0]["from"] == "Grok Bot" and mine[0]["from_type"] == "external"
            with pytest.raises(RuntimeError, match="not a member"):
                await call(client, "read_messages", room_id=secret["id"])
            with pytest.raises(RuntimeError, match="not a member"):
                await call(client, "post_message", room_id=secret["id"], text="sneaky")
            assert await call(client, "get_tasks") == []

        # The owner sees the message, sent by an external participant.
        items = (await c.get(f"/api/rooms/{general}/messages")).json()["items"]
        assert any(
            m["sender"]["kind"] == "external" and m["body"]["text"] == "Hello from Grok Bot" for m in items
        )

        rotated = (await c.post(f"/api/connections/{conn['id']}/rotate")).json()
        assert await raw_post(sim_srv, token) == 401, "the old token stops working at once"
        assert await raw_post(sim_srv, rotated["token"]) == 200
        revoked = (await c.post(f"/api/connections/{conn['id']}/revoke")).json()
        assert revoked["status"] == "disabled" and revoked["token"] is None
        assert await raw_post(sim_srv, rotated["token"]) == 401


async def test_only_the_owner_manages_connections(sim_srv: Server) -> None:
    async with httpx.AsyncClient(base_url=sim_srv.base_url) as anon:
        assert (
            await anon.post("/api/connections", json={"display_name": "X"}, headers={"X-CC-CSRF": "1"})
        ).status_code == 401
        assert (await anon.get("/api/connections")).status_code == 401


async def test_rate_limit(sim_srv: Server) -> None:
    async with logged_in(sim_srv) as c:
        token = (await connect(c))["token"]
    codes = [await raw_post(sim_srv, token) for _ in range(45)]
    assert codes[:40] == [200] * 40 and 429 in codes[40:]


async def test_review_with_grok_bot_over_mcp(fresh_database_url: str, tmp_path: Path) -> None:
    """Grok Bot shares its work over MCP; Claude and GPT (fake providers) review it and write a
    plan; Grok Bot responds. The run waits at each of Grok Bot's steps."""
    with run_fake_providers() as fake:
        env = dict(LIVE, ANTHROPIC_BASE_URL=fake, OPENAI_BASE_URL=f"{fake}/v1")
        with run_server(fresh_database_url, tmp_path, **env) as srv:
            async with logged_in(srv) as c:
                room_id, agents = await general_and_agents(c)
                conn = await connect(c)
                r = await c.post(
                    f"/api/rooms/{room_id}/runs",
                    json={
                        "goal": "Meme coin strategy research",
                        "workflow": "review",
                        "planner_id": agents["Claude"]["id"],
                        "critic_id": agents["GPT"]["id"],
                        "builder_id": conn["id"],
                        "budget_usd": 1.0,
                    },
                )
                assert r.status_code == 201, r.text
                run = r.json()
                assert (run["kind"], run["step"]) == ("review", "share")
                waiting = await wait_status(c, run["id"], {"waiting"})
                assert waiting["waiting_for"] == conn["id"]

                report = "H112 wallet basket: -0.030 SOL per trade over 44 trades.\n" + (
                    "detail line\n" * 4000
                )
                assert len(report) > 32_000, "long reports are split into parts"
                async with mcp(srv, conn["token"]) as client:
                    tasks = await call(client, "get_tasks")
                    assert len(tasks) == 1 and tasks[0]["run_id"] == run["id"] and tasks[0]["step"] == "share"
                    assert "Meme coin strategy research" in tasks[0]["instruction"]
                    assert "never suggest, instruct or perform real trades" in tasks[0]["instruction"]
                    done = await call(client, "submit_task", run_id=run["id"], text=report)
                    assert done["ok"] is True
                    with pytest.raises(RuntimeError, match="No task"):
                        await call(client, "submit_task", run_id=run["id"], text="again")

                    second = await wait_status(c, run["id"], {"waiting", "failed"}, within=40)
                    assert second["status"] == "waiting", second
                    tasks = await call(client, "get_tasks")
                    assert tasks[0]["step"] == "respond"
                    convo = tasks[0]["conversation"]
                    plan = [m for m in convo if m["from"] == "Claude"][-1]["text"]
                    assert "[FAKE PROVIDER]" in plan
                    await call(client, "submit_task", run_id=run["id"], text="Will run instructions 1 and 2.")

                final = await wait_status(c, run["id"], {"completed", "failed"})
                assert final["status"] == "completed", final
                assert final["turn_count"] == 6
                msgs = await run_messages(c, room_id, run["id"])
                chats = [
                    (m["sender"]["display_name"], m["body"]["text"][:14]) for m in msgs if m["kind"] == "chat"
                ]
                assert [n for n, _ in chats] == [
                    "Grok Bot",
                    "Grok Bot",
                    "Claude",
                    "GPT",
                    "Claude",
                    "Grok Bot",
                    "Claude",
                ]
                assert chats[0][1] == "[Part 1 of 2]\n"
                assert "Grok Bot shared its work" in msgs[-1]["body"]["text"]
                assert len(msgs[-1]["body"]["text"]) < 400, "the summary does not repeat a long goal"

                calls = await fake_calls(fake)
                assert (calls["anthropic"], calls["openai"]) == (3, 1)
                analyze = next(q["body"] for q in calls["requests"] if q["provider"] == "anthropic")
                prompt = analyze["messages"][-1]["content"]
                assert "H112 wallet basket" in prompt and "detail line" in prompt
                assert '"type": "external"' in prompt, "Grok Bot's text is labeled as external"
                rule = "never suggest, instruct or perform real trades"
                reviewer_calls = [
                    q["body"] for q in calls["requests"] if q["provider"] in ("anthropic", "openai")
                ]
                assert len(reviewer_calls) == 4
                assert all(rule in json.dumps(b) for b in reviewer_calls), (
                    "every reviewer step carries the rule"
                )
                anthropic_bodies = [q["body"] for q in calls["requests"] if q["provider"] == "anthropic"]
                assert [b["max_tokens"] for b in anthropic_bodies] == [12_000, 12_000, 8_000], "room to think"
                assert all(b["output_config"] == {"effort": "medium"} for b in anthropic_bodies)


async def test_cancel_a_waiting_run(sim_srv: Server) -> None:
    async with logged_in(sim_srv) as c:
        room_id, agents = await general_and_agents(c)
        conn = await connect(c)
        run = (
            await c.post(
                f"/api/rooms/{room_id}/runs",
                json={
                    "goal": "g",
                    "workflow": "review",
                    "planner_id": agents["Claude"]["id"],
                    "critic_id": agents["GPT"]["id"],
                    "builder_id": conn["id"],
                },
            )
        ).json()
        await wait_status(c, run["id"], {"waiting"})
        cancelled = (await c.post(f"/api/runs/{run['id']}/cancel")).json()
        assert cancelled["status"] == "cancelled" and cancelled["waiting_for"] is None
        async with mcp(sim_srv, conn["token"]) as client:
            assert await call(client, "get_tasks") == []
            with pytest.raises(RuntimeError, match="No task"):
                await call(client, "submit_task", run_id=run["id"], text="late")


async def test_external_agents_can_only_be_the_worker(sim_srv: Server) -> None:
    async with logged_in(sim_srv) as c:
        room_id, agents = await general_and_agents(c)
        conn = await connect(c)
        r = await c.post(
            f"/api/rooms/{room_id}/runs",
            json={
                "goal": "g",
                "workflow": "review",
                "planner_id": conn["id"],
                "critic_id": agents["GPT"]["id"],
                "builder_id": agents["Claude"]["id"],
            },
        )
        assert r.status_code == 422 and "planner_id" in r.text


async def test_waiting_runs_time_out(world: dict[str, Any]) -> None:  # noqa: F811
    sm = world["sm"]
    async with sm() as s:
        ext = models.Principal(id=f"ext_{uuid.uuid4().hex}", kind="external", display_name="Grok Bot")
        s.add(ext)
        await s.commit()
    run = await add_run(
        world,
        kind="review",
        status="waiting",
        step="share",
        planner_id=world["agents"]["Claude"].id,
        critic_id=world["agents"]["GPT"].id,
        builder_id=ext.id,
        agent_id=None,
        waiting_for=ext.id,
        waiting_since=datetime.now(UTC) - timedelta(hours=30),
    )
    port = ModelPort(cfg(world["url"]), sm, adapter_factory=lambda p, k: Adapter(), scope="t_wait")
    engine = BuiltinEngine(sm, port, world["coordinator"], Decimal("0.25"), simulated=False)
    assert await engine.expire_waiting(24) == 1
    async with sm() as s:
        r = await s.get(models.Run, run.id)
        assert (
            r is not None
            and r.status == "failed"
            and "No answer from Grok Bot within 24 hours" in (r.error or "")
        )
        err = await s.scalar(select(models.Message.body_text).where(models.Message.correlation_id == run.id))
        assert err is not None and "No answer from Grok Bot" in err


def test_split_text() -> None:
    assert split_text("short") == ["short"]
    text = "\n".join(f"line {i} " + "x" * 50 for i in range(2000))
    parts = split_text(text, limit=32_000)
    assert len(parts) == 4 and all(len(p) <= 32_000 for p in parts)
    assert parts[0].startswith("[Part 1 of 4]\n") and parts[-1].startswith("[Part 4 of 4]\n")
    body = "\n".join(p.split("\n", 1)[1] for p in parts)
    assert body.replace("\n", "") == text.replace("\n", ""), "nothing lost"


async def raw(srv: Server, method: str, token: str | None, body: Any = None) -> int:
    headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    async with httpx.AsyncClient(timeout=5) as h:
        return (await h.request(method, srv.mcp_url, json=body, headers=headers)).status_code


async def test_only_post_and_failed_auth_is_throttled(sim_srv: Server) -> None:
    async with logged_in(sim_srv) as c:
        token = (await connect(c))["token"]
    # A GET would open an endless stream; only POST is served.
    assert await raw(sim_srv, "GET", token) == 405
    assert await raw(sim_srv, "DELETE", token) == 405
    assert await raw_post(sim_srv, token) == 200  # Grok Bot is connected and polling
    # Unknown tokens are throttled across all callers (30 failures a minute) ...
    codes = [await raw_post(sim_srv, f"ccx_guess{i}") for i in range(35)]
    assert codes[:30] == [401] * 30 and codes[30:] == [429] * 5
    # ... while the token in active use keeps working.
    assert await raw_post(sim_srv, token) == 200


async def test_post_limits_and_reply_to_checks(sim_srv: Server) -> None:
    async with logged_in(sim_srv) as c:
        conn = await connect(c)
        other = (await c.post("/api/rooms", json={"name": "Other project"})).json()
        mine = (
            await c.post(
                f"/api/rooms/{other['id']}/messages",
                json={"kind": "chat", "body": {"text": "owner note"}, "idempotency_key": uuid.uuid4().hex},
            )
        ).json()
    async with mcp(sim_srv, conn["token"]) as client:
        room = (await call(client, "whoami"))["rooms"][0]["id"]
        with pytest.raises(RuntimeError, match="1 to 8000"):
            await call(client, "post_message", room_id=room, text="x" * 8001)
        with pytest.raises(RuntimeError, match="same room"):
            await call(client, "post_message", room_id=room, text="hi", reply_to=mine["id"])


async def test_concurrent_submissions_cannot_mix(sim_srv: Server) -> None:
    async with logged_in(sim_srv) as c:
        room_id, agents = await general_and_agents(c)
        conn = await connect(c)
        run = (
            await c.post(
                f"/api/rooms/{room_id}/runs",
                json={
                    "goal": "g",
                    "workflow": "review",
                    "planner_id": agents["Claude"]["id"],
                    "critic_id": agents["GPT"]["id"],
                    "builder_id": conn["id"],
                },
            )
        ).json()
        await wait_status(c, run["id"], {"waiting"})
        async with mcp(sim_srv, conn["token"]) as a, mcp(sim_srv, conn["token"]) as b:
            results = await asyncio.gather(
                call(a, "submit_task", run_id=run["id"], text="A" * 50_000),
                call(b, "submit_task", run_id=run["id"], text="B" * 50_000),
                return_exceptions=True,
            )
        assert sum(isinstance(x, dict) and x.get("ok") for x in results) == 1
        assert sum(isinstance(x, Exception) for x in results) == 1
        await wait_status(c, run["id"], {"waiting", "completed", "failed"})
        shared = [
            m
            for m in await run_messages(c, room_id, run["id"])
            if m["sender"]["kind"] == "external" and m["body"]["data"].get("step") == "share"
        ]
        letters = {m["body"]["text"].split("\n", 1)[1][0] for m in shared}
        assert len(shared) == 2 and len(letters) == 1, "both parts come from one submission"


async def test_timeout_never_fails_a_resumed_run(world: dict[str, Any]) -> None:  # noqa: F811
    sm = world["sm"]
    async with sm() as s:
        ext = models.Principal(id=f"ext_{uuid.uuid4().hex}", kind="external", display_name="Grok Bot")
        s.add(ext)
        await s.commit()
    old = datetime.now(UTC) - timedelta(hours=30)
    common = dict(
        kind="review",
        step="share",
        planner_id=world["agents"]["Claude"].id,
        critic_id=world["agents"]["GPT"].id,
        builder_id=ext.id,
        agent_id=None,
    )
    resumed = await add_run(world, status="queued", waiting_for=None, waiting_since=old, **common)
    submitting = await add_run(
        world,
        status="waiting",
        waiting_for=ext.id,
        waiting_since=old,
        lease_expires_at=datetime.now(UTC) + timedelta(minutes=2),
        **common,
    )
    port = ModelPort(cfg(world["url"]), sm, adapter_factory=lambda p, k: Adapter(), scope="t_wait2")
    engine = BuiltinEngine(sm, port, world["coordinator"], Decimal("0.25"), simulated=False)
    assert await engine.expire_waiting(24) == 0
    async with sm() as s:
        assert (await s.get(models.Run, resumed.id)).status == "queued"  # type: ignore[union-attr]
        assert (await s.get(models.Run, submitting.id)).status == "waiting"  # type: ignore[union-attr]


async def test_reviewers_see_the_whole_share_despite_chatter(world: dict[str, Any]) -> None:  # noqa: F811
    from command_center.messaging import service
    from command_center.orchestrator.context import build_request
    from command_center.orchestrator.engine import post_parts

    sm = world["sm"]
    run = await add_run(world)
    async with sm() as s:
        ext = models.Principal(id=f"ext_{uuid.uuid4().hex}", kind="external", display_name="Grok Bot")
        s.add(ext)
        await s.commit()
    share = "SUMMARY FIRST\n" + ("evidence line\n" * 4500)  # about 63,000 characters: 2 parts
    await post_parts(sm, run, ext.id, kind="chat", text=share, key="share:reply", reply_to=None, data={})
    async with sm() as s:
        sender = await s.get(models.Principal, ext.id)
        assert sender is not None
        for i in range(40):  # chatter after the share
            await service.append_message(
                s, world["room"].id, sender, kind="chat", text=f"noise {i}", idempotency_key=f"n{i}xxxxxx"
            )
    async with sm() as s:
        claude = await s.get(models.Principal, world["agents"]["Claude"].id)
        prof = await s.get(models.AgentProfile, world["agents"]["Claude"].id)
        assert claude is not None and prof is not None
        req = await build_request(
            s, room_id=world["room"].id, agent=claude, profile=prof, instruction="go", run_id=run.id
        )
    content = req.messages[0].content
    assert "SUMMARY FIRST" in content and "[Part 1 of 2]" in content and "[Part 2 of 2]" in content
    assert content.index("[Part 1 of 2]") < content.index("[Part 2 of 2]"), "parts in order"
