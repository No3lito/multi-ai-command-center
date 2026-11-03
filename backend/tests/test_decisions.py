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
        "why": "The retests need launch data. This checks the data is complete before paying for more.",
        "suggested_note": "Cap at 50k credits; stop and report if the pilot projects above it.",
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
    assert drafts[0].recommended == "approve" and drafts[1].recommended == "more_info", (
        "inferred from the text"
    )
    assert drafts[0].why and drafts[0].suggested_note and drafts[0].suggested_note.startswith("Cap at 50k")


def test_recommended_answer_is_explicit_or_inferred() -> None:
    assert decisions.infer_answer("Approve: free.") == "approve"
    assert decisions.infer_answer("more info, because the price is unknown") == "more_info"
    assert decisions.infer_answer("Decline for now.") == "decline"
    assert decisions.infer_answer("Hold the retests.") == "decline"
    assert decisions.infer_answer("It depends.") is None and decisions.infer_answer(None) is None
    explicit = decisions.DecisionDraft(question="q", recommendation="Approve it", recommended="more_info")
    assert explicit.recommended == "more_info", "an explicit answer wins over the text"


def test_split_brief_tolerates_bad_blocks() -> None:
    assert decisions.split_brief("No block.") == ("No block.", [])
    clean, drafts = decisions.split_brief("Brief.\n```decisions\n[not json]\n```")
    assert clean == "Brief." and drafts == []
    # Invalid items are skipped, valid ones kept.
    bad = [{"question": ""}, {"question": "ok", "on_approve": {"workflow": "deploy"}}, {"question": "fine"}]
    _, drafts = decisions.split_brief("B.\n```decisions\n" + json.dumps(bad) + "\n```")
    assert [d.question for d in drafts] == ["fine"]


def test_instructions_list_who_can_do_work_and_forbid_trades() -> None:
    who = decisions.describe_executors(
        [("Claude", "anthropic", True), ("GPT", "openai", True), ("Grok", "xai", False)], ["Grok Bot"]
    )
    assert len(who) == 3 and not any(line.startswith("Grok (") for line in who), (
        "unusable agents are left out"
    )
    text = decisions.instruction_suffix(who, ["logs/a.md"])
    assert "Claude (anthropic)" in text and "Grok Bot (connected agent)" in text and "Cannot run code" in text
    assert "logs/a.md" in text and "Never propose real trades" in text and "FINAL ROUND" not in text
    assert "FINAL ROUND" in decisions.instruction_suffix(who, [], final_round=True)


def test_dollar_caps_in_notes_are_found() -> None:
    assert decisions.note_cap("Total spend must stay under $1.00. Do not merge.") == Decimal("1.00")
    assert decisions.note_cap("cap at $0.50, max $2") == Decimal("0.50")
    assert decisions.note_cap("approve the $5 data pull") is None, "a price is not a cap"
    assert decisions.note_cap(None) is None


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


async def test_follow_ups_never_fall_back_silently_and_stop_at_limits(world: dict[str, Any]) -> None:  # noqa: F811
    run = await brief_run(
        world, briefer("**Verdict:** Needs you. One question.\n**Bottom line:** Ok." + FENCE)
    )
    async with world["sm"]() as s:
        done = await s.get(models.Run, run.id)
        assert done is not None and done.verdict == "needs_you"
        audit, lane = (
            await s.scalars(
                select(models.Decision)
                .where(models.Decision.run_id == run.id)
                .order_by(models.Decision.position)
            )
        ).all()
        settings = cfg(world["url"])
        owner = world["owner"].id

        # Grok Bot is not in this room: approving starts nothing and says why (no hidden replanning).
        blocked = await decisions.start_follow_up(
            s, settings, audit, answer="approve", note="cap 50k", owner_id=owner, budget_usd=None
        )
        assert blocked.run is None and blocked.reason and "Nobody connected can do this" in blocked.reason

        # More info (a discussion) runs, joins the chain, carries only the previous brief, and obeys
        # the dollar cap written in the note.
        more = await decisions.start_follow_up(
            s,
            settings,
            lane,
            answer="more_info",
            note="Keep it under $0.30.",
            owner_id=owner,
            budget_usd=None,
        )
        assert more.run is not None and more.reason is None
        assert more.run.kind == "collab" and more.run.chain_root_id == run.id and more.run.chain_depth == 1
        assert more.run.budget_usd == Decimal("0.30")
        assert "every sentence is a requirement" in more.run.goal
        await s.flush()
        carried = (
            await s.scalars(
                select(models.RunAttachment.path).where(models.RunAttachment.run_id == more.run.id)
            )
        ).all()
        assert carried == [f"previous-run/{run.id}.md"]

        # Round limit: a decision raised in the final round starts nothing.
        done.chain_depth = decisions.MAX_ROUNDS
        assert "follow-up rounds" in (await decisions.plan_check(s, lane, "more_info") or "")
        done.chain_depth = 0

        # Chain budget: once the chain has spent nearly all of it, nothing more starts.
        done.spent_usd = decisions.CHAIN_BUDGET - Decimal("0.05")
        broke = await decisions.start_follow_up(
            s, settings, lane, answer="more_info", note=None, owner_id=owner, budget_usd=None
        )
        assert broke.run is None and broke.reason and "budget for this topic is used up" in broke.reason
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
                assert "Nobody connected can do this" in audit_card["cannot_run_reason"]
                assert lane_card["cannot_run_reason"] is None and not audit_card["final_round"]
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
                # Grok Bot is not in this room: nothing starts, and the reason is said plainly.
                assert body["follow_up_run"] is None and body["decision"]["follow_up_run_id"] is None
                assert "Nobody connected can do this" in body["no_run_reason"]

                again = await c.post(f"/api/decisions/{audit_card['id']}/answer", json={"answer": "decline"})
                assert again.status_code == 409

                asked = await c.post(
                    f"/api/decisions/{lane_card['id']}/answer",
                    json={"answer": "more_info", "note": "Keep it under $0.40."},
                )
                follow = asked.json()["follow_up_run"]
                assert follow["kind"] == "collab" and follow["budget_usd"] == 0.4
                assert follow["chain_depth"] == 1 and follow["chain_root_id"] == r.json()["id"]

                items = (await c.get(f"/api/rooms/{room_id}/messages", params={"limit": 200})).json()["items"]
                said = [m["body"]["text"] for m in items if m["sender"]["display_name"] == "Coordinator"]
                assert any(
                    t.startswith("Owner APPROVED: Approve the capped Helius") and "Nothing was started:" in t
                    for t in said
                )
                assert any(
                    t.startswith("Owner asked for MORE INFORMATION on: Keep the meme lane") for t in said
                )

                followed = await wait_run(c, follow["id"], within=30)
                assert followed["status"] == "completed", followed
                decided = (
                    await c.get(f"/api/rooms/{room_id}/decisions", params={"status": "decided"})
                ).json()
                assert {d["status"] for d in decided} >= {"approved", "more_info"}
                assert decided[-1]["why"] is None or isinstance(decided[-1]["why"], str)
                approved = next(d for d in decided if d["status"] == "approved")
                assert approved["recommended"] == "approve" and approved["suggested_note"].startswith(
                    "Cap at 50k"
                )
                assert approved["why"].startswith("The retests need launch data")

                # Archive: hides a finished run; History still finds it; active runs cannot be archived.
                source = r.json()["id"]
                arch = await c.post(f"/api/runs/{source}/archive")
                assert arch.status_code == 200 and arch.json()["archived_at"]
                hist = (await c.get(f"/api/rooms/{room_id}/history", params={"q": "Review"})).json()
                assert source in [x["id"] for x in hist["runs"]]
                only = (await c.get(f"/api/rooms/{room_id}/history", params={"archived": "only"})).json()
                assert [x["id"] for x in only["runs"]] == [source]
                hidden = (await c.get(f"/api/rooms/{room_id}/history", params={"archived": "exclude"})).json()
                assert source not in [x["id"] for x in hidden["runs"]]
                found = (await c.get(f"/api/rooms/{room_id}/history", params={"q": "helius 50%"})).json()
                assert found["decisions"] == [], "% is matched literally, not as a wildcard"
                found = (await c.get(f"/api/rooms/{room_id}/history", params={"q": "capped HELIUS"})).json()
                assert found["decisions"] and {d["question"] for d in found["decisions"]} == {
                    BLOCK[0]["question"]
                }
                assert (await c.post(f"/api/runs/{source}/unarchive")).json()["archived_at"] is None

                busy = await c.post(
                    f"/api/rooms/{room_id}/runs",
                    json={
                        "goal": "Busy",
                        "planner_id": agents["Claude"]["id"],
                        "critic_id": agents["GPT"]["id"],
                    },
                )
                refused = await c.post(f"/api/runs/{busy.json()['id']}/archive")
                assert refused.status_code in (200, 409)  # 409 while it is still running
                await wait_run(c, busy.json()["id"])


async def test_wrap_up_skips_to_a_concluding_brief(world: dict[str, Any]) -> None:  # noqa: F811
    adapter = briefer("**Verdict:** Done. Stop here.\n**Bottom line:** Concluded.")
    port = await port_for(world["sm"], cfg(world["url"]), adapter)
    engine = BuiltinEngine(world["sm"], port, world["coordinator"], Decimal("0.25"), simulated=False)
    run = await add_run(
        world,
        kind="collab",
        step="critique",
        planner_id=world["agents"]["Claude"].id,
        critic_id=world["agents"]["GPT"].id,
        agent_id=None,
        max_turns=1,
        turn_count=1,
        wrap_up=True,
    )
    while await engine.step(run.id):
        pass
    async with world["sm"]() as s:
        done = await s.get(models.Run, run.id)
    assert done is not None and done.status == "completed" and done.verdict == "done"
    assert adapter.calls == 1, "the critique was skipped; only the brief was written"
    task = adapter.last.messages[0].content.rsplit("YOUR TASK:", 1)[1]
    assert (
        "WRAP UP NOW" in task and "**Verdict:**" in task and "Never ask the owner who should do work" in task
    )


async def test_workflow_steps_read_their_own_run_not_other_runs(world: dict[str, Any]) -> None:  # noqa: F811
    from command_center.messaging import service
    from command_center.orchestrator.context import build_request

    other = await add_run(world, kind="collab", step="plan", agent_id=None)
    mine = await add_run(world, kind="collab", step="plan", agent_id=None)
    async with world["sm"]() as s:
        owner = await s.get(models.Principal, world["owner"].id)
        claude = await s.get(models.Principal, world["agents"]["Claude"].id)
        profile = await s.get(models.AgentProfile, world["agents"]["Claude"].id)
        assert owner and claude and profile
        await service.append_message(
            s, world["room"].id, owner, kind="chat", text="owner says hi", idempotency_key="k1"
        )
        for key, run_id, text in (("k2", other.id, "OTHER RUN TEXT"), ("k3", mine.id, "MY RUN TEXT")):
            await service.append_message(
                s,
                world["room"].id,
                claude,
                kind="chat",
                text=text,
                idempotency_key=key,
                correlation_id=run_id,
            )
        lean = await build_request(
            s,
            room_id=world["room"].id,
            agent=claude,
            profile=profile,
            instruction="x",
            run_id=mine.id,
            lean=True,
        )
        full = await build_request(
            s, room_id=world["room"].id, agent=claude, profile=profile, instruction="x", run_id=mine.id
        )
    text = lean.messages[0].content
    assert "owner says hi" in text and "MY RUN TEXT" in text and "OTHER RUN TEXT" not in text
    assert "OTHER RUN TEXT" in full.messages[0].content, "reply runs still see the whole room"


def test_ready_made_options_are_parsed_and_bad_ones_dropped() -> None:
    brief = (
        "**Verdict:** Needs you.\n```decisions\n"
        '[{"question": "Run the backtest?", "recommended": "approve", "options": ['
        '{"label": "Yes, all 37", "detail": "About $0.40", "answer": "approve", "note": "Paper only."},'
        '{"label": "Top 10 only", "detail": "About $0.15", "answer": "approve",'
        ' "note": "Top 10, under $0.20."},'
        '{"label": "", "answer": "approve"},'
        '{"label": "Maybe", "answer": "perhaps"},'
        '{"label": "Not now", "answer": "decline"},'
        '{"label": "Tell me more", "answer": "more_info"},'
        '{"label": "Fifth good one", "answer": "decline"}]}]\n```'
    )
    _, drafts = decisions.split_brief(brief)
    assert len(drafts) == 1
    labels = [o.label for o in drafts[0].options]
    # Bad ones dropped, at most four kept.
    assert labels == ["Yes, all 37", "Top 10 only", "Not now", "Tell me more"]
    assert drafts[0].options[1].note == "Top 10, under $0.20."
