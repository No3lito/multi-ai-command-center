"""Design & build workflow: Claude and GPT co-design, Grok builds exactly what they specify.

FAKE PROVIDER / FAKE ADAPTER evidence only: proves orchestration, routing and limits, not
the quality of real model output.
"""

from __future__ import annotations

import os
import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic import SecretStr
from sqlalchemy import select, text

from command_center.db import models
from command_center.messaging import service
from command_center.orchestrator.context import build_request
from command_center.orchestrator.engine import BuiltinEngine
from command_center.providers.base import ChatRequest, ChatResponse
from command_center.providers.model_port import ModelPort
from tests.conftest import BACKEND, run_fake_providers, run_server
from tests.test_coordinator import fake_calls, general_and_agents, logged_in, run_messages, wait_run
from tests.test_review_fixes import add_run, cfg, world  # noqa: F401  (fixture)

INSERT_PRINCIPAL = (
    "INSERT INTO principals (id, kind, display_name, status) VALUES (:i, 'agent', :n, 'active')"
)
ALL_KEYS = {
    "ANTHROPIC_API_KEY": "sk-ant-fake",
    "OPENAI_API_KEY": "sk-openai-fake",
    "XAI_API_KEY": "xai-fake",
    "LIVE_BUDGET_USD": "2.00",
}


async def start_build(c: Any, room_id: str, agents: dict[str, Any], **extra: Any) -> Any:
    return await c.post(
        f"/api/rooms/{room_id}/runs",
        json={
            "goal": "A tip calculator web page",
            "workflow": "build",
            "planner_id": agents["Claude"]["id"],
            "critic_id": agents["GPT"]["id"],
            "builder_id": agents["Grok"]["id"],
            **extra,
        },
    )


async def test_design_and_build_through_the_live_code_path(fresh_database_url: str, tmp_path: Path) -> None:
    """FAKE PROVIDER: GPT's check is not APPROVED, so Grok applies fixes (7 agent turns)."""
    with run_fake_providers() as fake:
        env = dict(
            ALL_KEYS, ANTHROPIC_BASE_URL=fake, OPENAI_BASE_URL=f"{fake}/v1", XAI_BASE_URL=f"{fake}/xai/v1"
        )
        with run_server(fresh_database_url, tmp_path, **env) as srv:
            async with logged_in(srv) as c:
                room_id, agents = await general_and_agents(c)
                assert [agents[n]["role"] for n in ("Claude", "GPT", "Grok")] == [
                    "Co-designer",
                    "Co-designer",
                    "Builder",
                ]
                assert agents["Grok"]["model"] == "grok-build-0.1"
                r = await start_build(c, room_id, agents)
                assert r.status_code == 201, r.text
                run = r.json()
                assert (run["kind"], run["step"], run["builder_id"]) == (
                    "build",
                    "design",
                    agents["Grok"]["id"],
                )
                assert run["max_turns"] >= 7
                done = await wait_run(c, run["id"], within=40)
                assert done["status"] == "completed", done
                assert done["turn_count"] == 7
                msgs = await run_messages(c, room_id, run["id"])
                speakers = [m["sender"]["display_name"] for m in msgs if m["kind"] == "chat"]
                assert speakers == ["Claude", "GPT", "Grok", "Claude", "Grok", "GPT", "Grok"]
                assigns = [m["body"]["text"] for m in msgs if m["kind"] == "task.assign"]
                assert assigns[0] == "Step 1 of 7: @Claude, draft the design for: A tip calculator web page"
                assert assigns[-1].startswith("Step 7 of 7: @Grok, apply @GPT's fix instructions")
                summary = msgs[-1]
                assert (
                    summary["kind"] == "task.result" and "changed files in step 7" in summary["body"]["text"]
                )
                calls = await fake_calls(fake)
                assert (calls["anthropic"], calls["openai"], calls["xai"]) == (2, 2, 3)
                xai = [q["body"] for q in calls["requests"] if q["provider"] == "xai"]
                assert [b["max_output_tokens"] for b in xai] == [400, 8192, 8192]
                build_instruction = xai[1]["input"][-1]["content"]
                assert "exactly as Claude and GPT specified" in build_instruction
                assert "Do not substitute your own choices" in build_instruction
                assert "You are the builder" in xai[1]["input"][0]["content"]


class Scripted:
    """FAKE ADAPTER per provider; GPT approves the build when asked to check it."""

    simulated = False

    def __init__(self, provider: str) -> None:
        self.id = provider
        self.requests: list[ChatRequest] = []

    def capabilities(self, model: str):  # type: ignore[no-untyped-def]
        return None

    async def generate(self, req: ChatRequest) -> ChatResponse:
        self.requests.append(req)
        task = req.messages[-1].content.rsplit("YOUR TASK:", 1)[-1]
        if self.id == "openai" and "Check Grok's build" in task:
            reply = "**APPROVED.** The build matches the design."
        else:
            reply = f"[FAKE ADAPTER] {self.id} turn {len(self.requests)}"
        return ChatResponse(text=reply, input_tokens=100, output_tokens=50, model=req.model)


async def test_approved_build_skips_the_fix_step(world: dict[str, Any]) -> None:  # noqa: F811
    sm = world["sm"]
    adapters = {p: Scripted(p) for p in ("anthropic", "openai", "xai")}
    settings = cfg(world["url"]).model_copy(update={"xai_api_key": SecretStr("xai-fake")})
    port = ModelPort(settings, sm, adapter_factory=lambda p, k: adapters[p], scope="t_build")
    await port.ensure_cap()
    engine = BuiltinEngine(sm, port, world["coordinator"], Decimal("0.25"), simulated=False)
    async with sm() as s:
        grok = await s.scalar(select(models.Principal).where(models.Principal.display_name == "Grok"))
    assert grok is not None
    run = await add_run(
        world,
        kind="build",
        step="design",
        planner_id=world["agents"]["Claude"].id,
        critic_id=world["agents"]["GPT"].id,
        builder_id=grok.id,
        agent_id=None,
        max_turns=8,
    )
    for _ in range(10):
        if not await engine.step(run.id):
            break
    async with sm() as s:
        done = await s.get(models.Run, run.id)
        texts = (
            await s.scalars(
                select(models.Message.body_text)
                .where(models.Message.correlation_id == run.id)
                .order_by(models.Message.seq)
            )
        ).all()
    assert done is not None and done.status == "completed" and done.turn_count == 6
    assert not any(t.startswith("Step 7 of 7") for t in texts)
    assert "GPT approved the build" in texts[-1]
    assert len(adapters["xai"].requests) == 2  # feasibility note and build, no fix


async def test_build_run_validation(fresh_database_url: str, tmp_path: Path) -> None:
    with run_server(fresh_database_url, tmp_path, PROVIDER_MODE="simulated") as srv:
        async with logged_in(srv) as c:
            room_id, agents = await general_and_agents(c)
            no_builder = await start_build(c, room_id, agents, builder_id=None)
            assert no_builder.status_code == 422 and "builder_id is required" in no_builder.text
            same = await start_build(c, room_id, agents, builder_id=agents["Claude"]["id"])
            assert same.status_code == 422 and "different agent" in same.text
            collab_with_builder = await c.post(
                f"/api/rooms/{room_id}/runs",
                json={
                    "goal": "g",
                    "planner_id": agents["Claude"]["id"],
                    "critic_id": agents["GPT"]["id"],
                    "builder_id": agents["Grok"]["id"],
                },
            )
            assert collab_with_builder.status_code == 422
            ok = await start_build(c, room_id, agents)
            assert ok.status_code == 201
            done = await wait_run(c, ok.json()["id"], within=30)
            assert done["status"] == "completed" and done["simulated"] is True


async def test_builder_and_checker_see_the_whole_run(world: dict[str, Any]) -> None:  # noqa: F811
    sm = world["sm"]
    run = await add_run(world)
    big = "x" * 30_000
    async with sm() as s:
        gpt = await s.get(models.Principal, world["agents"]["GPT"].id)
        assert gpt is not None
        await service.append_message(
            s, world["room"].id, gpt, kind="chat", text="old " + big, idempotency_key="o1"
        )
        await service.append_message(
            s,
            world["room"].id,
            gpt,
            kind="chat",
            text="design " + big,
            idempotency_key="d1",
            correlation_id=run.id,
        )
    async with sm() as s:
        claude = await s.get(models.Principal, world["agents"]["Claude"].id)
        prof = await s.get(models.AgentProfile, world["agents"]["Claude"].id)
        assert claude is not None and prof is not None
        req = await build_request(
            s, room_id=world["room"].id, agent=claude, profile=prof, instruction="go", run_id=run.id
        )
    content = req.messages[0].content
    assert ("design " + big) in content, "this run's messages are kept whole"
    assert ("old " + big) not in content and "[truncated]" in content, "older messages are still trimmed"


async def test_migration_updates_default_roles_but_keeps_custom_ones(fresh_database_url: str) -> None:
    env = dict(os.environ, DATABASE_URL=fresh_database_url)

    def alembic(*args: str) -> None:
        subprocess.run(
            [sys.executable, "-m", "alembic", *args], cwd=BACKEND, env=env, check=True, capture_output=True
        )

    alembic("downgrade", "0005")
    old_claude = (
        "You lead planning. Turn goals into clear, ordered, testable steps, and say what you would "
        "verify. When reviewing others, be specific and kind."
    )
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(fresh_database_url.replace("postgresql://", "postgresql+asyncpg://", 1))
    try:
        async with engine.begin() as conn:
            for pid, name, role, prompt in (
                ("agt_a", "Claude", "Planner", old_claude),
                ("agt_b", "GPT", "My own role", "custom prompt"),
            ):
                await conn.execute(
                    text(INSERT_PRINCIPAL),
                    {"i": pid, "n": name},
                )
                await conn.execute(
                    text(
                        "INSERT INTO agent_profiles (principal_id, role, provider, model, system_prompt, "
                        "max_output_tokens, enabled) "
                        "VALUES (:i, :r, 'anthropic', 'claude-sonnet-5-5', :p, 2048, true)"
                    ),
                    {"i": pid, "r": role, "p": prompt},
                )
        alembic("upgrade", "head")
        async with engine.connect() as conn:
            rows = dict((await conn.execute(text("SELECT principal_id, role FROM agent_profiles"))).all())
    finally:
        await engine.dispose()
    assert rows == {"agt_a": "Co-designer", "agt_b": "My own role"}
