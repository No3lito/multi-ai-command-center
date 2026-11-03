"""Owner-attached files (read-only snapshots for the reviewers) and decision briefs.

FAKE PROVIDER / FAKE ADAPTER evidence: proves what is sent and stored, not model quality.
"""

from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from command_center import files
from command_center.db import models
from command_center.orchestrator.engine import BuiltinEngine, parse_waiting_on_you
from command_center.providers.base import ChatRequest, ChatResponse
from tests.conftest import run_fake_providers, run_server
from tests.test_coordinator import fake_calls, general_and_agents, logged_in, wait_run
from tests.test_review_fixes import Adapter, add_run, cfg, port_for, world  # noqa: F401  (fixture)

# ---------------------------------------------------------------- the files module


@pytest.fixture
def shared(tmp_path: Path) -> Path:
    root = tmp_path / "shared"
    (root / "logs").mkdir(parents=True)
    (root / "logs" / "LEARNING-LOG-full.md").write_text("H1 | chase cap | dead\nH123 | wait+trail | weak\n")
    (root / "README.md").write_text("# Trading review\n")
    (root / ".env").write_text("SECRET=1\n")
    (root / "chart.png").write_bytes(b"\x89PNG\x00\x00binary")
    (root / "fake.md").write_bytes(b"text\x00with a null byte")
    outside = tmp_path / "outside.md"
    outside.write_text("not yours")
    os.symlink(outside, root / "link-out.md")
    return root


def test_listing_hides_secrets_and_escapes(shared: Path) -> None:
    names = {e.name: e for e in files.list_dir(shared)}
    assert set(names) == {"logs", "README.md", "chart.png", "fake.md"}, "no .env, no link out of the folder"
    assert names["README.md"].readable and not names["chart.png"].readable
    assert [e.path for e in files.list_dir(shared, "logs")] == ["logs/LEARNING-LOG-full.md"]


@pytest.mark.parametrize(
    "bad", ["../outside.md", "/etc/passwd", "logs/../../outside.md", "C:/Windows/win.ini"]
)
def test_paths_cannot_leave_the_folder(shared: Path, bad: str) -> None:
    with pytest.raises(files.FileAccessError):
        files.read_snapshot(shared, bad)


@pytest.mark.parametrize("name", [".env", "chart.png", "fake.md", "link-out.md", "logs"])
def test_only_plain_text_files_inside_can_be_read(shared: Path, name: str) -> None:
    with pytest.raises(files.FileAccessError):
        files.read_snapshot(shared, name)


def test_snapshot(shared: Path) -> None:
    snap = files.read_snapshot(shared, "logs\\LEARNING-LOG-full.md")  # Windows-style separators work
    assert snap.path == "logs/LEARNING-LOG-full.md" and "H123" in snap.content and len(snap.sha256) == 64


# ---------------------------------------------------------------- the decision brief


def test_waiting_on_you_is_parsed() -> None:
    brief = """**Bottom line:** No edge at 5 s.
**Decided:**
- H123, H14, H52 are the retest candidates.
**Done:**
- Grok Bot saved HYPOTHESIS-REVIEW.md.
**Waiting on you:**
- Approve the launch coverage check (Helius credits, about 50k).
- Decide whether to continue the meme lane.
**Next steps:**
1. Grok Bot runs the coverage check after approval.
**Open risks:**
- Selection bias."""
    assert parse_waiting_on_you(brief) == [
        "Approve the launch coverage check (Helius credits, about 50k).",
        "Decide whether to continue the meme lane.",
    ]
    assert parse_waiting_on_you("**Waiting on you:** Nothing.\n**Next steps:**\n1. Rest.") == []
    assert parse_waiting_on_you("## Waiting on you\n1. Pick a domain.\n## Next steps\n- x") == [
        "Pick a domain."
    ]


async def test_brief_is_stored_with_pending_decisions(world: dict[str, Any]) -> None:  # noqa: F811
    class Briefer(Adapter):
        async def generate(self, req: ChatRequest) -> ChatResponse:
            self.calls += 1
            self.last = req
            return ChatResponse(
                text=(
                    "**Bottom line:** Ship it.\n**Waiting on you:**\n- Approve the $5 data pull.\n"
                    "**Next steps:**\n1. Go."
                ),
                input_tokens=10,
                output_tokens=40,
                model=req.model,
            )

    sm = world["sm"]
    adapter = Briefer()
    port = await port_for(sm, cfg(world["url"]), adapter)
    engine = BuiltinEngine(sm, port, world["coordinator"], Decimal("0.25"), simulated=False)
    run = await add_run(
        world,
        kind="collab",
        step="brief",
        planner_id=world["agents"]["Claude"].id,
        critic_id=world["agents"]["GPT"].id,
        agent_id=None,
        max_turns=8,
    )
    while await engine.step(run.id):
        pass
    async with sm() as s:
        done = await s.get(models.Run, run.id)
    assert done is not None and done.status == "completed"
    assert done.brief is not None and done.brief.startswith("**Bottom line:** Ship it.")
    assert done.pending_decisions == ["Approve the $5 data pull."]
    task = adapter.last.messages[0].content.rsplit("YOUR TASK:", 1)[1]
    assert all(
        h in task for h in ("**Bottom line:**", "**Waiting on you:**", "**Next steps:**", "**Open risks:**")
    )
    assert adapter.last.max_output_tokens == 8_000


async def test_brief_can_be_turned_off(world: dict[str, Any]) -> None:  # noqa: F811
    sm = world["sm"]
    adapter = Adapter()
    port = await port_for(sm, cfg(world["url"]), adapter)
    engine = BuiltinEngine(sm, port, world["coordinator"], Decimal("0.25"), simulated=False)
    run = await add_run(
        world,
        kind="collab",
        step="brief",
        planner_id=world["agents"]["Claude"].id,
        critic_id=world["agents"]["GPT"].id,
        agent_id=None,
        write_brief=False,
    )
    while await engine.step(run.id):
        pass
    async with sm() as s:
        done = await s.get(models.Run, run.id)
    assert done is not None and done.status == "completed" and done.brief is None and adapter.calls == 0


# ---------------------------------------------------------------- end to end


async def test_attachments_reach_the_reviewers_as_a_frozen_snapshot(
    fresh_database_url: str, tmp_path: Path, shared: Path
) -> None:
    with run_fake_providers() as fake:
        env = {
            "ANTHROPIC_API_KEY": "sk-ant-fake",
            "OPENAI_API_KEY": "sk-openai-fake",
            "ANTHROPIC_BASE_URL": fake,
            "OPENAI_BASE_URL": f"{fake}/v1",
            "LIVE_BUDGET_USD": "2.00",
            "FILES_ROOT": str(shared),
            "ATTACHMENT_MAX_CHARS": "5000",
        }
        with run_server(fresh_database_url, tmp_path, **env) as srv:
            async with logged_in(srv) as c:
                listing = (await c.get("/api/files")).json()
                assert listing["enabled"] is True
                assert {e["name"] for e in listing["entries"]} == {
                    "logs",
                    "README.md",
                    "chart.png",
                    "fake.md",
                }
                assert (await c.get("/api/files", params={"path": "../"})).status_code == 422
                room_id, agents = await general_and_agents(c)
                body = {
                    "goal": "Review the log",
                    "planner_id": agents["Claude"]["id"],
                    "critic_id": agents["GPT"]["id"],
                }
                bad = await c.post(
                    f"/api/rooms/{room_id}/runs", json={**body, "attachments": ["../outside.md"]}
                )
                assert bad.status_code == 422
                (shared / "big.md").write_text("x" * 6000)
                too_big = await c.post(f"/api/rooms/{room_id}/runs", json={**body, "attachments": ["big.md"]})
                assert too_big.status_code == 422 and "limit is 5,000" in too_big.text
                r = await c.post(
                    f"/api/rooms/{room_id}/runs",
                    json={**body, "attachments": ["logs/LEARNING-LOG-full.md", "README.md"]},
                )
                assert r.status_code == 201, r.text
                assert [a["path"] for a in r.json()["attachments"]] == [
                    "logs/LEARNING-LOG-full.md",
                    "README.md",
                ]
                # Changing the file after the run starts changes nothing: the run has a snapshot.
                (shared / "logs" / "LEARNING-LOG-full.md").write_text("EDITED LATER")
                done = await wait_run(c, r.json()["id"])
                assert done["status"] == "completed", done
                assert done["brief"] and "[FAKE PROVIDER]" in done["brief"]
                calls = await fake_calls(fake)
                anthropic_prompt = next(q["body"] for q in calls["requests"] if q["provider"] == "anthropic")[
                    "messages"
                ][-1]["content"]
                openai_prompt = next(q["body"] for q in calls["requests"] if q["provider"] == "openai")[
                    "input"
                ][-1]["content"]
                for prompt in (anthropic_prompt, openai_prompt):
                    assert prompt.startswith("ATTACHED FILES (chosen by the owner, read-only")
                    assert "path=logs/LEARNING-LOG-full.md" in prompt and "H123 | wait+trail | weak" in prompt
                    assert "EDITED LATER" not in prompt and "SECRET=1" not in prompt


async def test_files_are_off_without_a_shared_folder(fresh_database_url: str, tmp_path: Path) -> None:
    with run_server(fresh_database_url, tmp_path, PROVIDER_MODE="simulated") as srv:
        async with logged_in(srv) as c:
            assert (await c.get("/api/files")).json()["enabled"] is False
            room_id, agents = await general_and_agents(c)
            r = await c.post(
                f"/api/rooms/{room_id}/runs",
                json={
                    "goal": "g",
                    "planner_id": agents["Claude"]["id"],
                    "critic_id": agents["GPT"]["id"],
                    "attachments": ["README.md"],
                },
            )
            assert r.status_code == 422 and "no shared folder" in r.text
