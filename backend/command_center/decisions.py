"""Owner decisions: raised by a run's decision brief, answered on the dashboard.

The brief's author appends a machine-readable block (```decisions [...] ```) with, for each
"Waiting on you" item, a recommendation, the cost if known, and the follow-up runs the agents
prepared. The block is removed from the chat message and stored as Decision rows. When the
owner approves (or asks for more information), the prepared run starts at once, with the
owner's answer and note written into its goal so every agent, including external ones,
works within it. Every answer is also posted in the room and audited.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from command_center import files
from command_center.config import Settings
from command_center.db import models
from command_center.ids import new_id
from command_center.workspace import is_project_workspace, open_workspace

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


Answer = Literal["approve", "decline", "more_info"]


def infer_answer(recommendation: str | None) -> Answer | None:
    """The answer a free-text recommendation starts with ("Approve: ...", "More info, ...")."""
    head = (recommendation or "").strip().lower()[:40]
    if re.match(r"^(more info|need more info|more information|get more info)", head):
        return "more_info"
    if re.match(r"^(approve|yes|ratify)", head):
        return "approve"
    if re.match(r"^(decline|no\b|reject|hold|do not|don't)", head):
        return "decline"
    return None


class DecisionDraft(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    recommendation: str | None = Field(default=None, max_length=2000)
    recommended: Answer | None = None
    why: str | None = Field(default=None, max_length=2000)
    suggested_note: str | None = Field(default=None, max_length=2000)
    cost: str | None = Field(default=None, max_length=500)
    on_approve: OnApprove = Field(default_factory=OnApprove)
    on_more_info: OnMoreInfo = Field(default_factory=OnMoreInfo)

    def model_post_init(self, _context: Any) -> None:
        if self.recommended is None:
            self.recommended = infer_answer(self.recommendation)


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


def instruction_suffix(executors: list[str], attachments: list[str], *, final_round: bool = False) -> str:
    """What the brief's author is asked to append, so decisions can be answered with a click.

    executors: one line per participant saying what it can actually do (see describe_executors).
    """
    files_note = ", ".join(attachments) if attachments else "none"
    who = "\n".join(f"- {e}" for e in executors) or "- none"
    final = (
        " THIS IS THE FINAL ROUND of this topic: every on_approve and on_more_info workflow must be "
        '"none"; give the final recommendation in the brief instead of proposing more work.'
        if final_round
        else ""
    )
    return (
        "\n\nAfter the brief, add one fenced code block that starts with ```decisions and contains a "
        "JSON array with one object per 'Waiting on you' item (an empty array if there are none). "
        'Each object has: "question" (what the owner decides, one sentence), "why" (two or three '
        "plain-language sentences a busy owner who has not read the run can follow: the background "
        'and what is at stake, no jargon), "recommended" ("approve", "decline" or "more_info"), '
        '"recommendation" (that answer and the reason, one sentence), "suggested_note" (the note '
        "the owner should attach if they follow the recommendation: conditions, caps and what must "
        'be checked first, written as an instruction to the agents), "cost" (what it would cost if '
        'known, else "unknown"), "on_approve" (what runs if the owner approves: {"workflow": '
        '"review" | "build" | "collab" | "none", "worker": name or null, "goal": the full '
        'goal for that run, "attachments": file paths}), and "on_more_info" (what runs to get '
        'the missing facts: {"workflow", "worker", "goal"}).\n'
        f"Who can actually do work in this room, and what each can and cannot do:\n{who}\n"
        'Only name a worker from that list, and only for work it can do. Use "collab" only when '
        "another discussion between the reviewers would produce something new (not another plan "
        "for the same work). If the work needs someone who is not on the list (for example "
        'changing the Command Center\'s own code needs a coding agent), set workflow "none" and '
        "say so plainly in the question. Files available to attach: "
        f"{files_note}. Write goals that stand alone and include any limit the approval implies "
        "(for example a maximum spend). Never propose real trades, moving funds or changing live "
        "settings." + final
    )


def describe_executors(agents: list[tuple[str, str, bool]], externals: list[str]) -> list[str]:
    """agents: (name, provider, usable). External agents work with their own tools and files."""
    lines = []
    for name, provider, usable in agents:
        if not usable:
            continue
        lines.append(
            f"{name} ({provider}): reads the conversation and attached files and writes answers, "
            "designs, reviews and code as text. Cannot run code, open repositories or change files."
        )
    for name in externals:
        lines.append(
            f"{name} (connected agent): does tasks with its own tools, files and data, can read this "
            "project's folder and save to its outputs. Cannot change the Command Center's own code."
        )
    return lines


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
            recommended=d.recommended,
            why=d.why,
            suggested_note=d.suggested_note,
            cost=d.cost,
            follow_up={"on_approve": d.on_approve.model_dump(), "on_more_info": d.on_more_info.model_dump()},
            status="pending",
        )
        for i, d in enumerate(drafts)
    ]
    session.add_all(rows)
    return rows


MAX_ROUNDS = 2  # follow-up rounds after the owner-started run; the last one must conclude
CHAIN_BUDGET = Decimal("2.00")  # default total for one chain of follow-ups
MIN_RUN_BUDGET = Decimal("0.10")
_CAP = re.compile(
    r"(?:under|below|max(?:imum)?|cap(?:ped)?(?: at)?|limit(?:ed)?(?: to)?|within|at most|no more than|"
    r"budget(?: of)?|spend(?:ing)?(?: of)?)[^$\n]{0,30}\$\s?(\d+(?:\.\d{1,2})?)",
    re.IGNORECASE,
)


def note_cap(note: str | None) -> Decimal | None:
    """A dollar limit written in the owner's note ("under $1.00", "max $0.50"), if any."""
    if not note:
        return None
    caps = [Decimal(m.group(1)) for m in _CAP.finditer(note)]
    return min(caps) if caps else None


@dataclass
class FollowUpError(Exception):
    message: str


@dataclass
class FollowUp:
    """The result of answering: the run that started, or why none did (said plainly to everyone)."""

    run: models.Run | None
    reason: str | None = None


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


async def chain_spent(session: AsyncSession, root_id: str) -> Decimal:
    total = await session.scalar(
        select(func.coalesce(func.sum(models.Run.spent_usd), 0)).where(
            (models.Run.chain_root_id == root_id) | (models.Run.id == root_id)
        )
    )
    return Decimal(str(total or 0))


async def plan_check(
    session: AsyncSession, decision: models.Decision, answer: Literal["approve", "more_info"]
) -> str | None:
    """Why the prepared follow-up cannot run, or None if it can. Used for cards and answers."""
    source = await session.get(models.Run, decision.run_id)
    if source is None:
        return "The run that raised this decision no longer exists."
    plan: dict[str, Any] = (
        decision.follow_up.get("on_approve" if answer == "approve" else "on_more_info") or {}
    )
    workflow = str(plan.get("workflow") or ("collab" if answer == "more_info" else "none"))
    if workflow == "none":
        return None
    if (source.chain_depth or 0) >= MAX_ROUNDS:
        return (
            f"This topic already had {MAX_ROUNDS} follow-up rounds; "
            "the last brief is the final recommendation."
        )
    if workflow in ("review", "build"):
        worker = await _participant(session, decision.room_id, plan.get("worker"))
        if worker is None:
            name = plan.get("worker") or "the worker"
            return f"Nobody connected can do this: {name} is not available in this room."
    return None


async def start_follow_up(
    session: AsyncSession,
    settings: Settings,
    decision: models.Decision,
    *,
    answer: Literal["approve", "more_info"],
    note: str | None,
    owner_id: str,
    budget_usd: Decimal | None,
) -> FollowUp:
    """Create the run the agents prepared for this answer, or say plainly why none starts.

    No silent fallbacks: a missing worker, the round limit or a used-up chain budget start
    nothing, and the reason is returned so the owner and the agents see it.
    """
    source = await session.get(models.Run, decision.run_id)
    if source is None or source.planner_id is None or source.critic_id is None:
        raise FollowUpError("The run that raised this decision no longer exists.")
    plan: dict[str, Any] = (
        decision.follow_up.get("on_approve" if answer == "approve" else "on_more_info") or {}
    )
    workflow = str(plan.get("workflow") or ("collab" if answer == "more_info" else "none"))
    if workflow == "none":
        return FollowUp(None)
    blocked = await plan_check(session, decision, answer)
    if blocked:
        return FollowUp(None, blocked)

    root_id = source.chain_root_id or source.id
    depth = (source.chain_depth or 0) + 1
    budget = budget_usd if budget_usd is not None else max(source.budget_usd, DEFAULT_FOLLOW_UP_BUDGET)
    cap = note_cap(note)
    if cap is not None:
        budget = min(budget, cap)
    remaining = CHAIN_BUDGET - await chain_spent(session, root_id)
    budget = min(budget, remaining)
    if budget < MIN_RUN_BUDGET:
        return FollowUp(
            None,
            f"The budget for this topic is used up (${CHAIN_BUDGET:.2f} per chain of follow-ups).",
        )

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
        goal += f"\nOwner's note (every sentence is a requirement): {note.strip()}"
    if depth >= MAX_ROUNDS:
        goal += "\nThis is the final round on this topic: end with a final recommendation."
    goal = goal[:4000]

    worker = await _participant(session, decision.room_id, plan.get("worker"))
    if worker is not None and worker.id in (source.planner_id, source.critic_id):
        workflow, worker = "collab", None

    # Carry forward only the previous run's brief and final work, plus any files the plan names.
    ws = open_workspace(settings.files_root, settings.sources_root)
    snapshots: list[files.Snapshot] = []
    carried = await _previous_run_note(session, source)
    if carried is not None:
        snapshots.append(carried)
    if ws is not None:
        total = sum(s.chars for s in snapshots)
        for rel in [str(p) for p in plan.get("attachments") or []][: settings.attachment_max_files - 1]:
            try:
                snap = ws.read_snapshot(rel)
            except (files.FileAccessError, OSError):
                continue  # a file that moved or vanished is skipped, not fatal
            if total + snap.chars > settings.attachment_max_chars:
                break
            total += snap.chars
            snapshots.append(snap)

    run_id = new_id("run")
    room = await session.get(models.Room, decision.room_id)
    turns = {"build": 8, "review": 6}.get(workflow, 4) + 1  # +1 for picking project files
    run = models.Run(
        id=run_id,
        root_run_id=run_id,
        chain_root_id=root_id,
        chain_depth=depth,
        room_id=decision.room_id,
        kind=workflow,
        status="queued",
        step="select"
        if room is not None and room.project_path and is_project_workspace(ws)
        else {"build": "design", "review": "share"}.get(workflow, "plan"),
        goal=goal,
        planner_id=source.planner_id,
        critic_id=source.critic_id,
        builder_id=worker.id if worker is not None and workflow in ("review", "build") else None,
        max_turns=max(source.max_turns, turns),
        budget_usd=budget,
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
    return FollowUp(run)


async def _previous_run_note(session: AsyncSession, source: models.Run) -> files.Snapshot | None:
    """The previous run's brief and its last work message, as one read-only note."""
    last = None
    if source.last_message_id:
        msg = await session.get(models.Message, source.last_message_id)
        last = msg.body_text if msg is not None else None
    if not source.brief and not last:
        return None
    text = f"# Previous run\n\nGoal: {source.goal.strip()[:1500]}\n\n## Brief\n{source.brief or '(none)'}\n"
    if last and last.strip() != (source.brief or "").strip():
        text += f"\n## Its final message\n{last[:20_000]}\n"
    raw = text.encode()
    return files.Snapshot(
        path=f"previous-run/{source.id}.md",
        content=text,
        chars=len(text),
        sha256=hashlib.sha256(raw).hexdigest(),
    )
