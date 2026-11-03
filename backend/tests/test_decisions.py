"""Decision cards: briefs raise decisions, the owner answers them, approved work starts at once.

FAKE PROVIDER / FAKE ADAPTER evidence: proves parsing, storage, routing and run creation, not
model quality.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select

from command_center import decisions
from command_center.db import models
from command_center.orchestrator.engine import BuiltinEngine
from command_center.providers.base import ChatRequest, ChatResponse
from tests.conftest import run_fake_providers, run_server
from tests.test_coordinator import general_and_agents, logged_in, wait_run
from tests.test_review_fixes import Adapter, add_run, cfg, port_for, world  # noqa: F401  (fixture)

BLOCK = [
    {
        "question": "Approve the capped Helius coverage audit?",
        "recommendation": "Approve: it decides whether H123 can be tested at all.",
        "cost": "about 50k Helius credits",
        "on_approve": {
            "workflow": "review",
            "worker": "Grok Bot",
            "goal": "Run the coverage audit, at most 50k credits, and report.",
        },
        "on_more_info": {"workflow": "collab", "goal": "Estimate the audit's credit cost."},
    },
    {"question": "Keep the meme lane open?", "recommendation": "More info", "cost": "unknown"},
]
FENCE = "\n```decisions\n" + json.dumps(BLOCK) + "\n```"

# ---------------------------------------------------------------- parsing


def test_split_brief_takes_the_last_block_and_removes_it() -> None:
    text = "**Bottom line:** Go.\n```json\n[1, 2]\n```\nMore." + FENCE
    clean, drafts = decisions.split_brief(text)
    assert "```decisions" not in clean and clean.endswith("More.") and "[1, 2]" in clean
    assert [d.question for d in drafts] == [b["question"] for b in BLOCK]
    assert drafts[0].on_approve.workflow == "review" and drafts[0].on_approve.worker == "Grok Bot"
    assert drafts[1].on_approve.workflow == "none" and drafts[1].on_more_info.workflow == "collab"


def test_split_brief_tolerates_bad_blocks() -> None:
    assert decisions.split_brief("No block.") == ("No block.", [])
    clean, drafts = decisions.split_brief("Brief.\n```decisions\n[not json]\n```")
    assert clean == "Brief." and drafts == []
    # Invalid items are skipped, valid ones kept.
    bad = [{"question": ""}, {"question": "ok", "on_approve": {"workflow": "deploy"}}, {"question": "fine"}]
    _, drafts = decisions.split_brief("B.\n```decisions\n" + json.dumps(bad) + "\n```")
    assert [d.question for d in drafts] == ["fine"]


def test_instructions_name_participants_and_forbid_trades() -> None:
    text = decisions.instruction_suffix(["Claude", "GPT", "Grok Bot"], ["logs/a.md"])
    assert "Claude, GPT, Grok Bot" in text and "logs/a.md" in text and "Never propose real trades" in text


# ---------------------------------------------------------------- engine


def briefer(text: str) -> Adapter:
    class Briefer(Adapter):
        async def generate(self, req: ChatRequest) -> ChatResponse:
            self.calls += 1
            self.last = req
            return ChatResponse(text=text, input_tokens=10, output_tokens=40, model=req.model)

    return Briefer()


async def brief_run(w: dict[str, Any], adapter: Adapter) -> models.Run:
    port = await port_for(w["sm"], cfg(w["url"]), adapter)
    engine = BuiltinEngine(w["sm"], port, w["coordinator"], Decimal("0.25"), simulated=False)
    run = await add_run(
        w,
        kind="collab",
        step="brief",
        planner_id=w["agents"]["Claude"].id,
        critic_id=w["agents"]["GPT"].id,
        agent_id=None,
        max_turns=8,
    )
    while await engine.step(run.id):
        pass
    return run


async def test_brief_block_becomes_decisions_and_leaves_the_chat(world: dict[str, Any]) -> None:  # noqa: F811
    text = (
        "**Bottom line:** Retest H123.\n**Waiting on you:**\n- Approve the audit.\n- Keep the lane." + FENCE
    )
    run = await brief_run(world, briefer(text))
    async with world["sm"]() as s:
        done = await s.get(models.Run, run.id)
        rows = (
            await s.scalars(
                select(models.Decision)
                .where(models.Decision.run_id == run.id)
                .order_by(models.Decision.position)
            )
        ).all()
        posted = (
            await s.scalars(select(models.Message.body_text).where(models.Message.correlation_id == run.id))
        ).all()
    assert done is not None and done.status == "completed"
    assert done.brief is not None and "```decisions" not in done.brief
    assert all("```decisions" not in m for m in posted), "the block is not shown in the room"
    assert [r.question for r in rows] == [b["question"] for b in BLOCK]
    assert rows[0].cost == "about 50k Helius credits" and rows[0].status == "pending"
    assert done.pending_decisions == [b["question"] for b in BLOCK]


async def test_brief_without_block_falls_back_to_bullets(world: dict[str, Any]) -> None:  # noqa: F811
    run = await brief_run(world, briefer("**Bottom line:** Ok.\n**Waiting on you:**\n- Pick a domain.\n"))
    async with world["sm"]() as s:
        rows = (await s.scalars(select(models.Decision).where(models.Decision.run_id == run.id))).all()
    assert [r.question for r in rows] == ["Pick a domain."]
    assert rows[0].follow_up["on_approve"]["workflow"] == "none"


async def test_follow_up_without_its_worker_falls_back_to_the_reviewers(world: dict[str, Any]) -> None:  # noqa: F811
    run = await brief_run(world, briefer("**Bottom line:** Ok." + FENCE))
    async with world["sm"]() as s:
        d = await s.scalar(
            select(models.Decision).where(models.Decision.run_id == run.id, models.Decision.position == 0)
        )
        assert d is not None
        follow = await decisions.start_follow_up(
            s,
            cfg(world["url"]),
            d,
            answer="approve",
            note="cap 50k",
            owner_id=world["owner"].id,
            budget_usd=None,
        )
        assert follow is not None
        # Grok Bot is not in this room, so the designers handle it as a plan & review.
        assert follow.kind == "collab" and follow.builder_id is None
        assert follow.goal.startswith("Run the coverage audit")
        assert (
            "The owner APPROVED this decision" in follow.goal
            and "Owner's note (follow it): cap 50k" in follow.goal
        )
        assert follow.budget_usd == Decimal("1") and follow.write_brief
        await s.rollback()


# ---------------------------------------------------------------- API, end to end


async def test_owner_answers_decisions_from_the_dashboard(fresh_database_url: str, tmp_path: Path) -> None:
    with run_fake_providers(reply_suffix=FENCE) as fake:
        env = {
            "ANTHROPIC_API_KEY": "sk-ant-fake",
            "OPENAI_API_KEY": "sk-openai-fake",
            "ANTHROPIC_BASE_URL": fake,
            "OPENAI_BASE_URL": f"{fake}/v1",
            "LIVE_BUDGET_USD": "2.00",
        }
        with run_server(fresh_database_url, tmp_path, **env) as srv:
            async with logged_in(srv) as c:
                room_id, agents = await general_and_agents(c)
                r = await c.post(
                    f"/api/rooms/{room_id}/runs",
                    json={
                        "goal": "Review",
                        "planner_id": agents["Claude"]["id"],
                        "critic_id": agents["GPT"]["id"],
                    },
                )
                assert r.status_code == 201, r.text
                done = await wait_run(c, r.json()["id"])
                assert done["status"] == "completed", done

                pending = (
                    await c.get(f"/api/rooms/{room_id}/decisions", params={"status": "pending"})
                ).json()
                assert [d["question"] for d in pending] == [b["question"] for b in BLOCK]
                audit_card, lane_card = pending
                assert audit_card["on_approve"]["workflow"] == "review" and audit_card["run_goal"] == "Review"

                async with httpx.AsyncClient(base_url=srv.base_url, headers={"X-CC-CSRF": "1"}) as anon:
                    denied = await anon.post(
                        f"/api/decisions/{audit_card['id']}/answer", json={"answer": "approve"}
                    )
                    assert denied.status_code == 401

                ans = await c.post(
                    f"/api/decisions/{audit_card['id']}/answer",
                    json={"answer": "approve", "note": "cap 50k credits", "budget_usd": 0.4},
                )
                assert ans.status_code == 200, ans.text
                body = ans.json()
                assert (
                    body["decision"]["status"] == "approved"
                    and body["decision"]["owner_note"] == "cap 50k credits"
                )
                follow = body["follow_up_run"]
                assert follow is not None and body["decision"]["follow_up_run_id"] == follow["id"]
                assert follow["kind"] == "collab", "Grok Bot is not connected here, so the reviewers take it"
                assert follow["budget_usd"] == 0.4 and "cap 50k credits" in follow["goal"]

                again = await c.post(f"/api/decisions/{audit_card['id']}/answer", json={"answer": "decline"})
                assert again.status_code == 409

                declined = await c.post(
                    f"/api/decisions/{lane_card['id']}/answer", json={"answer": "decline"}
                )
                assert declined.status_code == 200 and declined.json()["follow_up_run"] is None

                items = (await c.get(f"/api/rooms/{room_id}/messages", params={"limit": 200})).json()["items"]
                said = [m["body"]["text"] for m in items if m["sender"]["display_name"] == "Coordinator"]
                assert any(t.startswith("Owner APPROVED: Approve the capped Helius") for t in said)
                assert any(t.startswith("Owner DECLINED: Keep the meme lane open?") for t in said)

                followed = await wait_run(c, follow["id"], within=30)
                assert followed["status"] == "completed", followed
                decided = (
                    await c.get(f"/api/rooms/{room_id}/decisions", params={"status": "decided"})
                ).json()
                assert {d["status"] for d in decided} == {"approved", "declined"}
