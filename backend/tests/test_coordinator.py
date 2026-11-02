"""Coordinator, agents, runs and usage through the real server process.

Three kinds of evidence, each labeled:
- SIMULATED: PROVIDER_MODE=simulated, deterministic stand-ins, no network, no cost.
- FAKE PROVIDER: live code path (keys, official SDKs, HTTP, cost, cap) against a local fake
  Anthropic/OpenAI server. Proves the plumbing and the money logic, not the real APIs.
- LIVE MODE WITHOUT KEYS: proves a missing key fails loudly instead of being faked.
"""

from __future__ import annotations

import asyncio
import itertools
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest

from tests.conftest import BACKEND as BACKEND_DIR
from tests.conftest import PASSWORD, Server, run_fake_providers, run_server


@asynccontextmanager
async def logged_in(srv: Server) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(base_url=srv.base_url, headers={"X-CC-CSRF": "1"}, timeout=10) as c:
        assert (await c.post("/api/auth/login", json={"password": PASSWORD})).status_code == 200
        yield c


async def general_and_agents(c: httpx.AsyncClient) -> tuple[str, dict[str, dict[str, Any]]]:
    rooms = (await c.get("/api/rooms")).json()
    general = next(r for r in rooms if r["name"] == "General")
    agents = {a["display_name"]: a for a in (await c.get("/api/agents")).json()}
    return general["id"], agents


async def fake_calls(fake: str) -> dict[str, Any]:
    async with httpx.AsyncClient() as c:
        return (await c.get(f"{fake}/calls")).json()  # type: ignore[no-any-return]


async def wait_run(c: httpx.AsyncClient, run_id: str, within: float = 20) -> dict[str, Any]:
    deadline = time.monotonic() + within
    while time.monotonic() < deadline:
        run = (await c.get(f"/api/runs/{run_id}")).json()
        if run["status"] not in ("queued", "running"):
            return run  # type: ignore[no-any-return]
        await asyncio.sleep(0.2)
    raise TimeoutError(f"run {run_id} still {run['status']}")


async def run_messages(c: httpx.AsyncClient, room_id: str, run_id: str) -> list[dict[str, Any]]:
    items = (await c.get(f"/api/rooms/{room_id}/messages", params={"limit": 200})).json()["items"]
    return [m for m in items if m["correlation_id"] == run_id]


async def start_collab(
    c: httpx.AsyncClient, room_id: str, agents: dict[str, dict[str, Any]], **extra: Any
) -> dict[str, Any]:
    r = await c.post(
        f"/api/rooms/{room_id}/runs",
        json={
            "goal": "Create a basic login interface",
            "planner_id": agents["Claude"]["id"],
            "critic_id": agents["GPT"]["id"],
            **extra,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()  # type: ignore[no-any-return]


# ---------------------------------------------------------------- SIMULATED


@pytest.fixture
def sim_server(fresh_database_url: str, tmp_path: Path):  # type: ignore[no-untyped-def]
    with run_server(fresh_database_url, tmp_path, PROVIDER_MODE="simulated") as srv:
        yield srv


async def test_simulated_collab_run_end_to_end(sim_server: Server) -> None:
    async with logged_in(sim_server) as c:
        room_id, agents = await general_and_agents(c)
        assert {agents["Claude"]["status"], agents["GPT"]["status"]} == {"simulated"}
        assert agents["Claude"]["provider"] == "anthropic" and agents["GPT"]["provider"] == "openai"
        run = await start_collab(c, room_id, agents)
        assert run["simulated"] is True
        done = await wait_run(c, run["id"])
        assert done["status"] == "completed", done
        assert done["turn_count"] == 3 and done["step"] == "done" and done["spent_usd"] == 0
        msgs = await run_messages(c, room_id, run["id"])
        assert [m["kind"] for m in msgs] == [
            "task.assign",
            "chat",
            "task.assign",
            "chat",
            "task.assign",
            "chat",
            "task.result",
        ]
        speakers = [m["sender"]["display_name"] for m in msgs if m["kind"] == "chat"]
        assert speakers == ["Claude", "GPT", "Claude"]
        for prev, m in itertools.pairwise(msgs):
            assert m["reply_to"] == prev["id"], "each step replies to the previous message"
        for m in msgs:
            if m["kind"] == "chat":
                assert m["body"]["data"]["simulated"] is True
                assert "Simulated response, no AI model was called" in m["body"]["text"]
                assert m["usage"]["cost_usd"] == 0
        usage = (await c.get("/api/usage")).json()
        assert usage["simulated_calls"] >= 3 and usage["spent_usd"] == 0


async def test_mention_creates_reply(sim_server: Server) -> None:
    async with logged_in(sim_server) as c:
        room_id, agents = await general_and_agents(c)
        claude = agents["Claude"]["id"]
        posted = (
            await c.post(
                f"/api/rooms/{room_id}/messages",
                json={
                    "kind": "chat",
                    "body": {"text": "@Claude what should we build first?"},
                    "mentions": [claude],
                    "idempotency_key": uuid.uuid4().hex,
                },
            )
        ).json()
        deadline = time.monotonic() + 15
        reply = None
        while time.monotonic() < deadline and reply is None:
            items = (
                await c.get(f"/api/rooms/{room_id}/messages", params={"after_seq": posted["seq"]})
            ).json()["items"]
            reply = next((m for m in items if m["reply_to"] == posted["id"]), None)
            await asyncio.sleep(0.2)
        assert reply is not None, "Claude should answer the mention"
        assert reply["sender"]["principal_id"] == claude and reply["body"]["data"]["simulated"] is True


async def test_run_validation_and_membership(sim_server: Server) -> None:
    async with logged_in(sim_server) as c:
        room_id, agents = await general_and_agents(c)
        same = await c.post(
            f"/api/rooms/{room_id}/runs",
            json={"goal": "x", "planner_id": agents["Claude"]["id"], "critic_id": agents["Claude"]["id"]},
        )
        assert same.status_code == 422
        room = (await c.post("/api/rooms", json={"name": f"Empty {uuid.uuid4().hex[:6]}"})).json()
        missing = await c.post(
            f"/api/rooms/{room['id']}/runs",
            json={"goal": "x", "planner_id": agents["Claude"]["id"], "critic_id": agents["GPT"]["id"]},
        )
        assert missing.status_code == 422
        for name in ("Claude", "GPT"):
            r = await c.post(f"/api/rooms/{room['id']}/members", json={"principal_id": agents[name]["id"]})
            assert r.status_code == 200
        ok = await start_collab(c, room["id"], agents, budget_usd=0.10)
        assert (await wait_run(c, ok["id"]))["status"] == "completed"
        too_much = await c.post(
            f"/api/rooms/{room_id}/runs",
            json={
                "goal": "x",
                "planner_id": agents["Claude"]["id"],
                "critic_id": agents["GPT"]["id"],
                "budget_usd": 50,
            },
        )
        assert too_much.status_code == 422


async def test_agent_management(sim_server: Server) -> None:
    async with logged_in(sim_server) as c:
        r = await c.post(
            "/api/agents",
            json={
                "display_name": "Gemma",
                "role": "Tester",
                "provider": "simulated",
                "model": "local-test",
                "max_output_tokens": 256,
            },
        )
        assert r.status_code == 201 and r.json()["status"] == "simulated"
        assert (
            await c.post("/api/agents", json={"display_name": "gemma", "provider": "simulated", "model": "x"})
        ).status_code == 409
        patched = await c.patch(f"/api/agents/{r.json()['id']}", json={"enabled": False})
        assert patched.json()["status"] == "disabled"
        bad = await c.post(
            "/api/agents",
            json={
                "display_name": "Bad",
                "provider": "openai",
                "model": "gpt-6.1-sol",
                "max_output_tokens": 100000,
            },
        )
        assert bad.status_code == 422


# ---------------------------------------------------------------- LIVE MODE, NO KEYS


async def test_live_mode_without_keys_fails_loudly(server: Server, client: httpx.AsyncClient) -> None:
    room_id, agents = await general_and_agents(client)
    assert agents["Claude"]["status"] == "missing_key" and agents["GPT"]["status"] == "missing_key"
    run = await start_collab(client, room_id, agents)
    assert run["simulated"] is False
    done = await wait_run(client, run["id"])
    assert done["status"] == "failed" and "No API key configured for anthropic" in done["error"]
    kinds = [m["kind"] for m in await run_messages(client, room_id, run["id"])]
    assert kinds == ["task.assign", "error"], "no fake agent answer may appear"


# ---------------------------------------------------------------- FAKE PROVIDER (live code path)


async def test_live_code_path_with_fake_providers(fresh_database_url: str, tmp_path: Path) -> None:
    with run_fake_providers() as fake:
        env = {
            "ANTHROPIC_API_KEY": "sk-ant-fake",
            "OPENAI_API_KEY": "sk-openai-fake",
            "ANTHROPIC_BASE_URL": fake,
            "OPENAI_BASE_URL": f"{fake}/v1",
            "LIVE_BUDGET_USD": "1.00",
        }
        with run_server(fresh_database_url, tmp_path, **env) as srv:
            async with logged_in(srv) as c:
                room_id, agents = await general_and_agents(c)
                assert agents["Claude"]["status"] == "live" and agents["GPT"]["status"] == "live"
                run = await start_collab(c, room_id, agents)
                done = await wait_run(c, run["id"])
                assert done["status"] == "completed", done
                calls = await fake_calls(fake)
                assert (calls["anthropic"], calls["openai"]) == (2, 1)
                assert calls["models"] == ["claude-sonnet-5-5", "gpt-6.1-sol", "claude-sonnet-5-5"]
                # 100 input + 50 output tokens per call at $2/$10 per 1M = $0.0007 per call.
                assert done["spent_usd"] == pytest.approx(0.0021)
                usage = (await c.get("/api/usage")).json()
                assert usage["spent_usd"] == pytest.approx(0.0021) and usage["reserved_usd"] == 0
                assert usage["remaining_usd"] == pytest.approx(1.0 - 0.0021)
                chats = [m for m in await run_messages(c, room_id, run["id"]) if m["kind"] == "chat"]
                assert all(m["body"]["data"]["simulated"] is False for m in chats)
                assert all("[FAKE PROVIDER]" in m["body"]["text"] for m in chats)


async def test_exhausted_cap_sends_no_requests(fresh_database_url: str, tmp_path: Path) -> None:
    with run_fake_providers() as fake:
        env = {
            "ANTHROPIC_API_KEY": "sk-ant-fake",
            "OPENAI_API_KEY": "sk-openai-fake",
            "ANTHROPIC_BASE_URL": fake,
            "OPENAI_BASE_URL": f"{fake}/v1",
            "LIVE_BUDGET_USD": "0.001",
        }
        with run_server(fresh_database_url, tmp_path, **env) as srv:
            async with logged_in(srv) as c:
                room_id, agents = await general_and_agents(c)
                done = await wait_run(c, (await start_collab(c, room_id, agents))["id"])
                assert done["status"] == "budget_exceeded"
                assert "No request was sent to the provider" in done["error"]
                assert (await fake_calls(fake))["anthropic"] == 0


async def test_cancel_during_model_call(fresh_database_url: str, tmp_path: Path) -> None:
    with run_fake_providers(delay=2.0) as fake:
        env = {
            "ANTHROPIC_API_KEY": "sk-ant-fake",
            "OPENAI_API_KEY": "sk-openai-fake",
            "ANTHROPIC_BASE_URL": fake,
            "OPENAI_BASE_URL": f"{fake}/v1",
        }
        with run_server(fresh_database_url, tmp_path, **env) as srv:
            async with logged_in(srv) as c:
                room_id, agents = await general_and_agents(c)
                run = await start_collab(c, room_id, agents)
                await asyncio.sleep(0.8)  # the planner's call is in flight
                cancelled = (await c.post(f"/api/runs/{run['id']}/cancel")).json()
                assert cancelled["status"] == "cancelled"
                await asyncio.sleep(2.5)
                final = (await c.get(f"/api/runs/{run['id']}")).json()
                assert final["status"] == "cancelled"
                kinds = [m["kind"] for m in await run_messages(c, room_id, run["id"])]
                assert "chat" not in kinds, "no agent message is posted after cancellation"
                usage = (await c.get("/api/usage")).json()
                assert usage["spent_usd"] > 0, "the in-flight call is still paid for and recorded"


async def test_live_check_command_with_fake_providers(fresh_database_url: str, tmp_path: Path) -> None:
    """FAKE PROVIDER: the owner's `command-center live-check` runs end to end and reports cost."""
    import os
    import subprocess
    import sys

    with run_fake_providers() as fake:
        env = {
            "ANTHROPIC_API_KEY": "sk-ant-fake",
            "OPENAI_API_KEY": "sk-openai-fake",
            "ANTHROPIC_BASE_URL": fake,
            "OPENAI_BASE_URL": f"{fake}/v1",
            "LIVE_BUDGET_USD": "10.00",
        }
        with run_server(fresh_database_url, tmp_path, **env):  # seeds the Claude and GPT agents
            pass
        proc = await asyncio.to_thread(
            subprocess.run,
            [sys.executable, "-m", "command_center.cli", "live-check"],
            cwd=BACKEND_DIR,
            env=dict(os.environ, DATABASE_URL=fresh_database_url, OWNER_PASSWORD=PASSWORD, **env),
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert "[anthropic] OK  model=claude-haiku-5-5" in proc.stdout
        assert "[openai] OK  model=gpt-6-luna" in proc.stdout
        assert "of $10.00 cap" in proc.stdout
        assert (await fake_calls(fake))["models"] == ["claude-haiku-5-5", "gpt-6-luna"]
