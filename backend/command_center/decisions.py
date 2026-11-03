"""Owner decisions: raised by a run's decision brief, answered on the dashboard.

The brief's author appends a machine-readable block (```decisions [...] ```) with, for each
"Waiting on you" item, a recommendation, the cost if known, and the follow-up runs the agents
prepared. The block is removed from the chat message and stored as Decision rows. When the
owner approves (or asks for more information), the prepared run starts at once, with the
owner's answer and note written into its goal so every agent, including external ones,
works within it. Every answer is also posted in the room and audited.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from command_center import files
from command_center.config import Settings
from command_center.db import models
from command_center.ids import new_id

MAX_DECISIONS = 10
DEFAULT_FOLLOW_UP_BUDGET = Decimal("0.50")
_BLOCK = re.compile(r"```(?:decisions|json)?[ \t]*\n(\[[\s\S]*?\])\s*```", re.IGNORECASE)

Workflow = Literal["review", "build", "collab", "none"]


class OnApprove(BaseModel):
    workflow: Workflow = "none"
    worker: str | None = Field(default=None, max_length=80)
    goal: str = Field(default="", max_length=4000)
    attachments: list[str] = Field(default_factory=list, max_length=10)


class OnMoreInfo(BaseModel):
    workflow: Workflow = "collab"
    worker: str | None = Field(default=None, max_length=80)
    goal: str = Field(default="", max_length=4000)


class DecisionDraft(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    recommendation: str | None = Field(default=None, max_length=2000)
    cost: str | None = Field(default=None, max_length=500)
    on_approve: OnApprove = Field(default_factory=OnApprove)
    on_more_info: OnMoreInfo = Field(default_factory=OnMoreInfo)


def split_brief(text: str) -> tuple[str, list[DecisionDraft]]:
    """The brief without its decisions block, and the decisions in it (empty if absent or invalid)."""
    match = None
    for m in _BLOCK.finditer(text):
        match = m  # the last block is the decisions block
    if match is None:
        return text, []
    clean = (text[: match.start()] + text[match.end() :]).strip()
    try:
        raw = json.loads(match.group(1))
    except json.JSONDecodeError:
        return clean, []
    drafts: list[DecisionDraft] = []
    if isinstance(raw, list):
        for item in raw[:MAX_DECISIONS]:
            try:
                drafts.append(DecisionDraft.model_validate(item))
            except ValidationError:
                continue
    return clean, drafts


def instruction_suffix(participants: list[str], attachments: list[str]) -> str:
    """What the brief's author is asked to append, so decisions can be answered with a click."""
    files_note = ", ".join(attachments) if attachments else "none"
    return (
        "\n\nAfter the brief, add one fenced code block that starts with ```decisions and contains a "
        "JSON array with one object per 'Waiting on you' item (an empty array if there are none). "
        'Each object has: "question" (what the owner decides, one sentence), "recommendation" '
        '(approve, decline or more info, and why, one sentence), "cost" (what it would cost if '
        'known, else "unknown"), "on_approve" (what runs if the owner approves: {"workflow": '
        '"review" | "build" | "collab" | "none", "worker": name or null, "goal": the full '
        'goal for that run, "attachments": file paths}), and "on_more_info" (what runs to get '
        'the missing facts: {"workflow", "worker", "goal"}). Use "review" when an agent such '
        'as a connected one must do work and report back, "collab" for analysis by the reviewers '
        'only, and "none" when approval needs no further work. Participants you may name as '
        f"worker: {', '.join(participants) or 'none'}. Files available to attach: {files_note}. "
        "Write goals that stand alone and include any limit the approval implies (for example a "
        "maximum spend). Never propose real trades, moving funds or changing live settings."
    )


def drafts_from_bullets(items: list[str]) -> list[DecisionDraft]:
    """Fallback when the brief has no valid block: one decision per "Waiting on you" bullet."""
    return [DecisionDraft(question=item[:2000]) for item in items[:MAX_DECISIONS]]


async def store(session: AsyncSession, run: models.Run, drafts: list[DecisionDraft]) -> list[models.Decision]:
    rows = [
        models.Decision(
            id=new_id("dec"),
            room_id=run.room_id,
            run_id=run.id,
            position=i,
            question=d.question,
            recommendation=d.recommendation,
            cost=d.cost,
            follow_up={"on_approve": d.on_approve.model_dump(), "on_more_info": d.on_more_info.model_dump()},
            status="pending",
        )
        for i, d in enumerate(drafts)
    ]
    session.add_all(rows)
    return rows


@dataclass
class FollowUpError(Exception):
    message: str


async def _participant(session: AsyncSession, room_id: str, name: str | None) -> models.Principal | None:
    if not name:
        return None
    rows = await session.scalars(
        select(models.Principal)
        .join(models.RoomMember, models.RoomMember.principal_id == models.Principal.id)
        .where(models.RoomMember.room_id == room_id, models.Principal.status == "active")
    )
    wanted = name.strip().lower()
    return next((p for p in rows.all() if p.display_name.lower() == wanted), None)


async def start_follow_up(
    session: AsyncSession,
    settings: Settings,
    decision: models.Decision,
    *,
    answer: Literal["approve", "more_info"],
    note: str | None,
    owner_id: str,
    budget_usd: Decimal | None,
) -> models.Run | None:
    """Create the run the agents prepared for this answer. None when the plan needs no run."""
    source = await session.get(models.Run, decision.run_id)
    if source is None or source.planner_id is None or source.critic_id is None:
        raise FollowUpError("The run that raised this decision no longer exists.")
    plan: dict[str, Any] = (
        decision.follow_up.get("on_approve" if answer == "approve" else "on_more_info") or {}
    )
    workflow = str(plan.get("workflow") or ("collab" if answer == "more_info" else "none"))
    if workflow == "none":
        return None
    verdict = (
        "The owner APPROVED this decision" if answer == "approve" else "The owner needs MORE INFORMATION"
    )
    base_goal = str(plan.get("goal") or "").strip() or (
        f"Get the owner the facts needed to decide: {decision.question}"
        if answer == "more_info"
        else f"Carry out the approved decision: {decision.question}"
    )
    goal = f"{base_goal}\n\n{verdict}: {decision.question}"
    if note:
        goal += f"\nOwner's note (follow it): {note.strip()}"
    goal = goal[:4000]

    worker = await _participant(session, decision.room_id, plan.get("worker"))
    if workflow in ("review", "build") and worker is None:
        workflow = "collab"  # nobody to do the work: the reviewers handle it
    if worker is not None and worker.id in (source.planner_id, source.critic_id):
        workflow, worker = "collab", None

    # Re-read attachments now, from the plan or the source run, so the follow-up sees current files.
    wanted: list[str] = [str(p) for p in plan.get("attachments") or []]
    if not wanted:
        wanted = list(
            (
                await session.scalars(
                    select(models.RunAttachment.path).where(models.RunAttachment.run_id == source.id)
                )
            ).all()
        )
    snapshots: list[files.Snapshot] = []
    root = settings.files_root
    if wanted and files.available(root):
        assert root is not None
        total = 0
        for rel in wanted[: settings.attachment_max_files]:
            try:
                snap = files.read_snapshot(root, rel)
            except (files.FileAccessError, OSError):
                continue  # a file that moved or vanished is skipped, not fatal
            if total + snap.chars > settings.attachment_max_chars:
                break
            total += snap.chars
            snapshots.append(snap)

    run_id = new_id("run")
    turns = {"build": 8, "review": 6}.get(workflow, 4)
    run = models.Run(
        id=run_id,
        root_run_id=run_id,
        room_id=decision.room_id,
        kind=workflow,
        status="queued",
        step={"build": "design", "review": "share"}.get(workflow, "plan"),
        goal=goal,
        planner_id=source.planner_id,
        critic_id=source.critic_id,
        builder_id=worker.id if worker is not None and workflow in ("review", "build") else None,
        max_turns=max(source.max_turns, turns),
        budget_usd=budget_usd if budget_usd is not None else max(source.budget_usd, DEFAULT_FOLLOW_UP_BUDGET),
        spent_usd=Decimal(0),
        simulated=source.simulated,
        write_brief=True,
        created_by=owner_id,
    )
    session.add(run)
    await session.flush()
    for snap in snapshots:
        session.add(
            models.RunAttachment(
                id=new_id("att"),
                run_id=run.id,
                path=snap.path,
                content=snap.content,
                chars=snap.chars,
                sha256=snap.sha256,
            )
        )
    return run
