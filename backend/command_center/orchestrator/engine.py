"""Coordinator: the replaceable orchestration engine interface and the built-in engine.

Engines never call providers or the database directly for side effects that matter: model
calls go through ModelPort (budget reservation), and messages go through the messaging
service (ordering, idempotency). Each step posts with a deterministic idempotency key, so a
step re-run after a crash never duplicates a message.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Protocol

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from command_center import decisions, project_files
from command_center.db import models
from command_center.files import FileAccessError
from command_center.ids import new_id
from command_center.messaging import service
from command_center.orchestrator.context import build_request
from command_center.providers.base import ProviderError
from command_center.providers.model_port import BudgetExceeded, ModelPort, ProviderNotReady
from command_center.workspace import Workspace

log = logging.getLogger(__name__)

MAX_REPLY_HOPS = 3
MAX_MENTIONS_PER_MESSAGE = 5
DEFAULT_MAX_RUNS_PER_TREE = 10
COLLAB_STEPS = ("plan", "critique", "revise", "brief", "summary")
# Design & build: two co-designers with one goal direct a builder. The builder adds a short
# build note, implements the final design exactly (including any code-level instructions),
# and applies the co-designer's fix instructions if the check finds problems.
BUILD_STEPS = ("design", "codesign", "feasibility", "finalize", "build", "check", "fix", "brief", "summary")
APPROVED = "APPROVED"
# Review & improve: an agent (often an external one such as Grok Bot) shares its work, two
# co-reviewers analyze it and write a plan, and the agent says how it will carry it out.
REVIEW_STEPS = ("share", "analyze", "ideas", "plan", "respond", "brief", "summary")
# Returned by _agent_turn when the step belongs to an external agent: the run now waits.
WAITING = "__waiting__"
# Applies to every step of a review, for reviewers and the worker alike.
RESEARCH_ONLY = (
    "Keep all of this to research, analysis, backtests and paper tests: never suggest, instruct "
    "or perform real trades, moving funds, or changes to live settings or accounts. Those are "
    "the owner's decisions alone."
)
FEASIBILITY_MAX_TOKENS = 400
# Reviewer and designer steps: room for the model's thinking plus a long answer (thinking
# tokens count toward the limit on Claude 5.5 and GPT reasoning models).
DEEP_STEP_MAX_TOKENS = 12_000
BRIEF_MAX_TOKENS = 8_000
BRIEF_HEADINGS = ("Bottom line", "Decided", "Done", "Waiting on you", "Next steps", "Open risks")
BUILD_MAX_TOKENS = 8192
FINISHED = {"completed", "failed", "cancelled", "budget_exceeded"}


class OrchestrationEngine(Protocol):
    """Replaceable engine (LangGraph or Microsoft Agent Framework are evaluated in Phase 3)."""

    name: str

    async def step(self, run_id: str) -> bool:
        """Advance the run by one step. Returns True while the run still has work left."""
        ...


def steps_for(kind: str) -> tuple[str, ...]:
    return {"build": BUILD_STEPS, "review": REVIEW_STEPS}.get(kind, COLLAB_STEPS)


def next_step(step: str, kind: str = "collab") -> str:
    steps = steps_for(kind)
    i = steps.index(step)
    return steps[i + 1] if i + 1 < len(steps) else "done"


def find_mentions(text: str, agents: list[models.Principal]) -> list[models.Principal]:
    """Agents addressed as @Name in text (case-insensitive, whole name)."""
    found: list[models.Principal] = []
    for agent in agents:
        pattern = r"(?<![\w@])@" + re.escape(agent.display_name) + r"(?![\w])"
        if re.search(pattern, text, re.IGNORECASE):
            found.append(agent)
    return found


async def room_agents(session: AsyncSession, room_id: str) -> list[models.Principal]:
    stmt = (
        select(models.Principal)
        .join(models.RoomMember, models.RoomMember.principal_id == models.Principal.id)
        .join(models.AgentProfile, models.AgentProfile.principal_id == models.Principal.id)
        .where(
            models.RoomMember.room_id == room_id,
            models.Principal.kind == "agent",
            models.AgentProfile.enabled.is_(True),
        )
    )
    return list((await session.scalars(stmt)).all())


async def room_externals(session: AsyncSession, room_id: str) -> list[models.Principal]:
    """Connected external agents (for example Grok Bot over MCP) that are members of the room."""
    stmt = (
        select(models.Principal)
        .join(models.RoomMember, models.RoomMember.principal_id == models.Principal.id)
        .where(
            models.RoomMember.room_id == room_id,
            models.Principal.kind == "external",
            models.Principal.status == "active",
        )
    )
    return list((await session.scalars(stmt)).all())


async def create_reply_runs(
    session: AsyncSession,
    *,
    room_id: str,
    trigger: models.Message | None,
    trigger_id: str,
    agent_ids: list[str],
    created_by: str,
    hop: int,
    budget_usd: Decimal,
    simulated: bool,
    root_run_id: str | None = None,
    tree_budget_usd: Decimal | None = None,
    max_runs_per_tree: int = DEFAULT_MAX_RUNS_PER_TREE,
) -> list[models.Run]:
    """One reply run per mentioned agent that is an enabled member of the room.

    Every run belongs to a tree. root_run_id=None starts a new tree (a human message): the
    first run is the root and carries the tree budget, its siblings join it. Agent-triggered
    runs pass their parent's root. A tree never grows past max_runs_per_tree runs, and all of
    its runs share the root's budget (enforced by ModelPort before each paid call).
    """
    if hop > MAX_REPLY_HOPS:
        return []
    members = {a.id: a for a in await room_agents(session, room_id)}
    wanted = [a for a in list(dict.fromkeys(agent_ids))[:MAX_MENTIONS_PER_MESSAGE] if a in members]
    room_left = max_runs_per_tree
    if root_run_id is not None:
        root = await session.scalar(select(models.Run).where(models.Run.id == root_run_id).with_for_update())
        if root is None or root.status not in ("queued", "running", "completed"):
            await session.commit()
            return []  # tree cancelled or failed: no new branches
        in_tree = await session.scalar(
            select(func.count())
            .select_from(models.Run)
            .where((models.Run.root_run_id == root_run_id) | (models.Run.id == root_run_id))
        )
        room_left = max_runs_per_tree - int(in_tree or 0)
        if room_left < len(wanted):
            log.info(
                "run tree %s reached %d runs; dropping %d mentions",
                root_run_id,
                max_runs_per_tree,
                len(wanted) - max(room_left, 0),
            )
    runs: list[models.Run] = []
    for agent_id in wanted[: max(room_left, 0)]:
        run_id = new_id("run")
        new_root = root_run_id or (runs[0].id if runs else run_id)
        is_root = new_root == run_id
        run = models.Run(
            id=run_id,
            root_run_id=new_root,
            room_id=room_id,
            kind="reply",
            status="queued",
            step="reply",
            goal=(trigger.body_text[:500] if trigger else ""),
            agent_id=agent_id,
            trigger_message_id=trigger_id,
            last_message_id=trigger_id,
            hop=hop,
            max_turns=1,
            budget_usd=(tree_budget_usd or budget_usd) if is_root else budget_usd,
            spent_usd=Decimal(0),
            simulated=simulated,
            created_by=created_by,
        )
        session.add(run)
        runs.append(run)
    await session.commit()
    return runs


def short_goal(goal: str, limit: int = 160) -> str:
    """The goal's first line, shortened, for summaries (the full goal is in step 1)."""
    first = goal.strip().splitlines()[0] if goal.strip() else ""
    first = first.rstrip(" .")
    return first if len(first) <= limit else first[: limit - 3].rstrip() + "..."


def parse_waiting_on_you(brief: str) -> list[str]:
    """The items under the brief's "Waiting on you" heading; empty when there are none."""
    items: list[str] = []
    inside = False
    for raw in brief.splitlines():
        line = raw.strip()
        bare = line.strip("*#_ ").lower()
        heading = next((h for h in BRIEF_HEADINGS if bare.startswith(h.lower())), None)
        if heading is not None:
            inside = heading == "Waiting on you"
            rest = line.split(":", 1)[1].strip().strip("*_ ") if ":" in line else ""
            if inside and rest and rest.lower().rstrip(".") not in ("nothing", "none", "n/a"):
                items.append(rest)
            continue
        if (inside and line[:1] in "-*•") or (inside and line[:2].rstrip(".").isdigit()):
            item = line.lstrip("-*• ").split(". ", 1)[-1] if line[:1].isdigit() else line.lstrip("-*• ")
            item = item.strip()
            if item and item.lower().rstrip(".") not in ("nothing", "none", "n/a"):
                items.append(item)
    return items[:20]


MESSAGE_TEXT_LIMIT = 32_000  # CCMP v1 body.text maxLength


def split_text(text: str, limit: int = MESSAGE_TEXT_LIMIT) -> list[str]:
    """Split text into parts that fit one message, at line breaks where possible, each part
    labeled "[Part i of n]" when there is more than one."""
    if len(text) <= limit:
        return [text]
    room = limit - 40  # space for the part label
    chunks: list[str] = []
    rest = text
    while rest:
        if len(rest) <= room:
            chunks.append(rest)
            break
        cut = rest.rfind("\n", room // 2, room)
        cut = cut if cut > 0 else room
        chunks.append(rest[:cut])
        rest = rest[cut:].lstrip("\n")
    n = len(chunks)
    return [f"[Part {i} of {n}]\n{c}" for i, c in enumerate(chunks, 1)]


async def post_parts(
    sessionmaker: async_sessionmaker[AsyncSession],
    run: models.Run,
    sender_id: str,
    *,
    kind: str,
    text: str,
    key: str,
    reply_to: str | None,
    data: dict[str, object],
    usage: dict[str, object] | None = None,
    mentions: list[str] | None = None,
) -> str:
    """Post a run message, as numbered parts if it is over the message limit. The first part
    uses `key` (so a step's answer is always found at f"{run.id}:{step}:reply"), later parts
    key:2, key:3... Usage is attached to the first part only. Returns the last part's id."""
    last = reply_to
    message_id = ""
    for i, part in enumerate(split_text(text), 1):
        async with sessionmaker() as s:
            sender = await s.get(models.Principal, sender_id)
            assert sender is not None
            result = await service.append_message(
                s,
                run.room_id,
                sender,
                kind=kind,
                text=part,
                idempotency_key=f"{run.id}:{key}" if i == 1 else f"{run.id}:{key}:{i}",
                reply_to=last,
                mentions=mentions if i == 1 else None,
                data=data if i == 1 else {**data, "part": i},
                usage=usage if i == 1 else None,
                correlation_id=run.id,
            )
            message_id = result.message.id
            last = message_id
    return message_id


class BuiltinEngine:
    name = "builtin"

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        models_port: ModelPort,
        coordinator_id: str,
        reply_budget_usd: Decimal,
        simulated: bool,
        max_runs_per_tree: int = DEFAULT_MAX_RUNS_PER_TREE,
        workspace: Callable[[], Workspace | None] | None = None,
        attachment_max_files: int = 10,
        attachment_max_chars: int = 300_000,
    ) -> None:
        self.max_runs_per_tree = max_runs_per_tree
        # The owner's project workspace (None when no folder is configured).
        self.workspace = workspace or (lambda: None)
        self.attachment_max_files = attachment_max_files
        self.attachment_max_chars = attachment_max_chars
        self.sessionmaker = sessionmaker
        self.models = models_port
        self.coordinator_id = coordinator_id
        self.reply_budget_usd = reply_budget_usd
        self.simulated = simulated
        # Unmodified answers of steps that use a postprocess hook (the decision brief).
        self.raw_answers: dict[str, str] = {}

    # ------------------------------------------------------------ helpers

    async def _post(
        self,
        run: models.Run,
        sender_id: str,
        *,
        kind: str,
        text: str,
        key: str,
        reply_to: str | None,
        data: dict[str, object],
        usage: dict[str, object] | None = None,
        mentions: list[str] | None = None,
    ) -> str:
        """Post a run message. Text over the message limit is posted as numbered parts (keys
        key, key:2, key:3...); returns the id of the last part."""
        return await post_parts(
            self.sessionmaker,
            run,
            sender_id,
            kind=kind,
            text=text,
            key=key,
            reply_to=reply_to,
            data=data,
            usage=usage,
            mentions=mentions,
        )

    async def _load(self, run_id: str) -> models.Run | None:
        async with self.sessionmaker() as s:
            return await s.get(models.Run, run_id)

    async def _update(self, run_id: str, **values: object) -> None:
        async with self.sessionmaker() as s:
            run = await s.get(models.Run, run_id, with_for_update=True)
            if run is None:
                return
            if run.status in FINISHED:
                # Already ended (for example cancelled by the owner while a step ran): never
                # resurrect it or overwrite its final status.
                return
            for key, value in values.items():
                setattr(run, key, value)
            if values.get("status") in FINISHED:
                run.finished_at = datetime.now(UTC)
                run.lease_expires_at = None
            await s.commit()

    async def _fail(self, run: models.Run, status: str, reason: str) -> None:
        await self._post(
            run,
            self.coordinator_id,
            kind="error",
            text=reason,
            key="error",
            reply_to=run.last_message_id,
            data={"run_id": run.id, "status": status},
        )
        await self._update(run.id, status=status, error=reason)

    async def expire_waiting(self, timeout_hours: float) -> int:
        """Fail runs that have waited longer than timeout_hours for an external agent."""
        cutoff = datetime.now(UTC) - timedelta(hours=timeout_hours)
        async with self.sessionmaker() as s:
            # One statement: a run resumed by a submission in the meantime is no longer
            # 'waiting' and is left alone. Runs being submitted right now (claimed) are skipped.
            failed = (
                await s.execute(
                    update(models.Run)
                    .where(
                        models.Run.status == "waiting",
                        models.Run.waiting_since < cutoff,
                        (models.Run.lease_expires_at.is_(None)) | (models.Run.lease_expires_at < func.now()),
                    )
                    .values(status="failed", finished_at=func.now(), lease_expires_at=None)
                    .returning(models.Run.id, models.Run.waiting_for)
                )
            ).all()
            names = {
                p.id: p.display_name
                for p in (
                    await s.scalars(
                        select(models.Principal).where(models.Principal.id.in_([w for _, w in failed if w]))
                    )
                ).all()
            }
            for run_id, waiting_for in failed:
                reason = (
                    f"No answer from {names.get(waiting_for or '', 'the external agent')} "
                    f"within {timeout_hours:g} hours."
                )
                await s.execute(update(models.Run).where(models.Run.id == run_id).values(error=reason))
            await s.commit()
        for run_id, _waiting_for in failed:
            run = await self._load(run_id)
            if run is not None:
                await self._post(
                    run,
                    self.coordinator_id,
                    kind="error",
                    text=run.error or "Timed out.",
                    key="error",
                    reply_to=run.last_message_id,
                    data={"run_id": run.id, "status": "failed"},
                )
        return len(failed)

    # ------------------------------------------------------------ agent turn

    async def _agent_turn(
        self,
        run: models.Run,
        agent_id: str,
        instruction: str,
        step_key: str,
        reply_to: str | None,
        max_output_tokens: int | None = None,
        postprocess: Callable[[str], str] | None = None,
    ) -> str | None:
        """One model call plus the agent's message. Returns the message id, or None if the run ended.

        postprocess: rewrites the answer before it is posted; the unmodified answer is kept in
        self.raw_answers[run.id] for the caller."""
        async with self.sessionmaker() as s:
            # A previous attempt of this exact step may have posted its answer and then crashed
            # before the run advanced. Reuse it instead of paying for the same call again.
            existing = await s.scalar(
                select(models.Message.id).where(
                    models.Message.sender_id == agent_id,
                    models.Message.idempotency_key == f"{run.id}:{step_key}:reply",
                )
            )
        if existing is not None:
            log.info("run %s step %s already answered; not calling the model again", run.id, step_key)
            await self._update(run.id, last_message_id=existing)
            return existing
        if run.turn_count >= run.max_turns:
            await self._fail(run, "failed", f"Turn limit reached ({run.max_turns}).")
            return None
        async with self.sessionmaker() as s:
            agent = await s.get(models.Principal, agent_id)
            profile = await s.get(models.AgentProfile, agent_id)
            if agent is not None and agent.kind == "external":
                if agent.status != "active":
                    await self._fail(run, "failed", f"{agent.display_name} is disconnected.")
                    return None
                # Hand the step to the external agent (it picks it up over MCP) and pause.
                await self._update(
                    run.id,
                    status="waiting",
                    waiting_for=agent_id,
                    waiting_instruction=instruction,
                    waiting_since=datetime.now(UTC),
                )
                log.info("run %s step %s is waiting for %s", run.id, step_key, agent.display_name)
                return WAITING
            if agent is None or profile is None:
                await self._fail(run, "failed", "Agent no longer exists.")
                return None
            req = await build_request(
                s, room_id=run.room_id, agent=agent, profile=profile, instruction=instruction, run_id=run.id
            )
            if max_output_tokens is not None:
                req = replace(req, max_output_tokens=max_output_tokens)
            name = agent.display_name
        try:
            result = await self.models.call(profile, req, run_id=run.id, simulated=run.simulated)
        except BudgetExceeded as exc:
            await self._fail(
                run, "budget_exceeded", f"{name} was not called: {exc}. No request was sent to the provider."
            )
            return None
        except ProviderNotReady as exc:
            await self._fail(run, "failed", f"{name} could not run: {exc.message}")
            return None
        except ProviderError as exc:
            await self._fail(run, "failed", f"{name} failed: {exc.message} ({exc.code}).")
            return None
        current = await self._load(run.id)
        if current is None or current.status == "cancelled":
            return None  # cancelled while the model was thinking; usage is still recorded
        text = result.response.text.strip()
        if not text:
            # Usually the whole output budget went to thinking. Say so plainly instead of
            # posting an empty message, and stop the run so it can be rerun with more room.
            reason = (
                f"{name} used its whole output limit ({req.max_output_tokens} tokens) on thinking "
                "and wrote no answer. The call was still paid for. Raise the limit or rerun."
                if result.response.truncated
                else f"{name} returned an empty answer."
            )
            await self._fail(run, "failed", reason)
            return None
        if postprocess is not None:
            self.raw_answers[run.id] = text
            text = postprocess(text) or "(no brief text)"
        if result.response.truncated:
            text += (
                f"\n\n[Cut off: this answer reached {name}'s output limit of {req.max_output_tokens} tokens.]"
            )
        async with self.sessionmaker() as s:
            mentioned = [
                a.id for a in find_mentions(text, await room_agents(s, run.room_id)) if a.id != agent_id
            ]
        msg_id = await self._post(
            run,
            agent_id,
            kind="chat",
            text=text,
            key=f"{step_key}:reply",
            reply_to=reply_to,
            mentions=mentioned,
            data={
                "run_id": run.id,
                "step": step_key,
                "provider": result.provider,
                "model": result.response.model,
                "simulated": result.simulated,
            },
            usage={
                "input_tokens": result.response.input_tokens,
                "output_tokens": result.response.output_tokens,
                "cost_usd": float(result.cost_usd),
            },
        )
        await self._update(run.id, turn_count=run.turn_count + 1, last_message_id=msg_id)
        # Only free conversation (reply runs) spawns replies. A collab run already decides who
        # speaks next; letting its messages trigger replies too made agents answer in parallel.
        if mentioned and run.kind == "reply" and run.hop < MAX_REPLY_HOPS:
            async with self.sessionmaker() as s:
                msg = await s.get(models.Message, msg_id)
                await create_reply_runs(
                    s,
                    room_id=run.room_id,
                    trigger=msg,
                    trigger_id=msg_id,
                    agent_ids=mentioned,
                    created_by=run.created_by,
                    hop=run.hop + 1,
                    budget_usd=self.reply_budget_usd,
                    simulated=run.simulated,
                    root_run_id=run.root_run_id or run.id,
                    max_runs_per_tree=self.max_runs_per_tree,
                )
        return msg_id

    # ------------------------------------------------------------ steps

    async def step(self, run_id: str) -> bool:
        run = await self._load(run_id)
        if run is None or run.status in FINISHED:
            return False
        if run.kind == "reply":
            return await self._reply_step(run)
        if run.step == "select":
            return await self._select_step(run)
        if run.step == "brief":
            return await self._brief_step(run)
        if run.kind == "build":
            return await self._build_step(run)
        if run.kind == "review":
            return await self._review_step(run)
        return await self._collab_step(run)

    async def _reply_step(self, run: models.Run) -> bool:
        assert run.agent_id is not None
        async with self.sessionmaker() as s:
            trigger = await s.get(models.Message, run.trigger_message_id) if run.trigger_message_id else None
            sender = await s.get(models.Principal, trigger.sender_id) if trigger else None
        who = sender.display_name if sender else "someone"
        msg_id = await self._agent_turn(
            run,
            run.agent_id,
            f"Reply to the latest message from {who}, which mentions you. Answer it directly.",
            "reply",
            run.trigger_message_id,
        )
        if msg_id is not None and msg_id != WAITING:
            await self._update(run.id, status="completed", step="done")
        return False

    async def _collab_step(self, run: models.Run) -> bool:
        assert run.planner_id is not None and run.critic_id is not None
        async with self.sessionmaker() as s:
            planner = await s.get(models.Principal, run.planner_id)
            critic = await s.get(models.Principal, run.critic_id)
        if planner is None or critic is None:
            await self._fail(run, "failed", "A participating agent no longer exists.")
            return False
        p, c = planner.display_name, critic.display_name
        plans = {
            "plan": (
                run.planner_id,
                f"Step 1 of 3: @{p}, propose a plan for: {run.goal}",
                f"Propose a concrete, step-by-step plan for this goal: {run.goal}",
            ),
            "critique": (
                run.critic_id,
                f"Step 2 of 3: @{c}, review @{p}'s plan.",
                f"Critique {p}'s plan above for the goal '{run.goal}': gaps, risks, and "
                "specific improvements. Do not rewrite the whole plan.",
            ),
            "revise": (
                run.planner_id,
                f"Step 3 of 3: @{p}, revise the plan using @{c}'s critique.",
                f"Revise your plan using {c}'s critique. Output the final plan only.",
            ),
        }
        if run.step in plans:
            agent_id, announce, instruction = plans[run.step]
            assign_id = await self._post(
                run,
                self.coordinator_id,
                kind="task.assign",
                text=announce,
                key=f"{run.step}:assign",
                reply_to=run.last_message_id,
                data={"run_id": run.id, "status": "running", "step": run.step},
            )
            msg_id = await self._agent_turn(
                run, agent_id, instruction, run.step, assign_id, DEEP_STEP_MAX_TOKENS
            )
            if msg_id is None or msg_id == WAITING:
                return False
            await self._update(run.id, step=next_step(run.step))
            return True
        if run.step == "summary":
            fresh = await self._load(run.id)
            spent = fresh.spent_usd if fresh else run.spent_usd
            label = "simulated, no API cost" if run.simulated else f"real API cost ${spent:.4f}"
            text = (
                f"Run complete. {p} planned, {c} reviewed, and {p} produced the revised plan above "
                f"for: {short_goal(run.goal)}. {run.turn_count} agent turns, {label}."
            )
            await self._post(
                run,
                self.coordinator_id,
                kind="task.result",
                text=text,
                key="summary",
                reply_to=run.last_message_id,
                data={"run_id": run.id, "status": "completed"},
            )
            await self._update(run.id, status="completed", step="done")
        return False

    async def _build_step(self, run: models.Run) -> bool:
        assert run.planner_id is not None and run.critic_id is not None and run.builder_id is not None
        async with self.sessionmaker() as s:
            designer = await s.get(models.Principal, run.planner_id)
            codesigner = await s.get(models.Principal, run.critic_id)
            builder = await s.get(models.Principal, run.builder_id)
        if designer is None or codesigner is None or builder is None:
            await self._fail(run, "failed", "A participating agent no longer exists.")
            return False
        p, c, b = designer.display_name, codesigner.display_name, builder.display_name
        shared = (
            f"You and {c if run.step != 'codesign' else p} are co-designers with the same goal: give "
            f"the owner exactly what they need for: {run.goal}."
        )
        plans: dict[str, tuple[str, str, str, int | None]] = {
            "design": (
                run.planner_id,
                f"Step 1 of 7: @{p}, draft the design for: {run.goal}",
                f"{shared} Draft the design: what will be built, its structure and files, the key "
                f"decisions, and how to check that it works. {b} will build exactly what the final "
                "design says, including any code-level instructions (language, libraries, names, "
                "patterns), so be specific wherever it matters.",
                DEEP_STEP_MAX_TOKENS,
            ),
            "codesign": (
                run.critic_id,
                f"Step 2 of 7: @{c}, improve the design together with @{p}.",
                f"{shared} Improve {p}'s draft as an equal partner: fix gaps and risks, simplify, "
                "and add what is missing, including code-level instructions where they matter. "
                "Say clearly what you changed and why. Do not write the implementation.",
                DEEP_STEP_MAX_TOKENS,
            ),
            "feasibility": (
                run.builder_id,
                f"Step 3 of 7: @{b}, quick build check.",
                f"You will build this design exactly as {p} and {c} direct. In under 120 words, "
                "note only what would block or complicate building it, or say it is ready to "
                "build. This is minor input: do not redesign it and do not write code.",
                FEASIBILITY_MAX_TOKENS,
            ),
            "finalize": (
                run.planner_id,
                f"Step 4 of 7: @{p}, finalize the design with @{c}'s improvements and @{b}'s note.",
                f"{shared} Write the final design that you and {c} agree on, folding in {c}'s "
                f"improvements and {b}'s build note. This is the specification {b} will build "
                "from: complete and concrete, with no open questions unless they truly block.",
                DEEP_STEP_MAX_TOKENS,
            ),
            "build": (
                run.builder_id,
                f"Step 5 of 7: @{b}, build it exactly as designed.",
                f"Build the final design above exactly as {p} and {c} specified, including every "
                "code-level instruction (language, libraries, names, structure). Do not substitute "
                "your own choices. Output the complete implementation: every file with its path "
                "as a heading and its full contents in a code block, then a short instruction for "
                "running it. Only if something in the design truly cannot work, follow it as "
                "closely as possible and say where in one line.",
                BUILD_MAX_TOKENS,
            ),
            "check": (
                run.critic_id,
                f"Step 6 of 7: @{c}, check the build against the design.",
                f"Check {b}'s build against the final design. If it matches and works, reply "
                f"with {APPROVED} as the first word and nothing that needs changing. Otherwise "
                f"give {b} numbered fix instructions, most important first, precise enough to "
                "apply without guessing (file, what to change, what it should be). Do not "
                "rewrite the code yourself.",
                DEEP_STEP_MAX_TOKENS,
            ),
            "fix": (
                run.builder_id,
                f"Step 7 of 7: @{b}, apply @{c}'s fix instructions.",
                f"Apply {c}'s numbered fix instructions above exactly, and change nothing else. "
                "Output every changed file in full, with its path as a heading and its contents "
                "in a code block, then one line per instruction saying how it was applied.",
                BUILD_MAX_TOKENS,
            ),
        }
        if run.step == "fix" and await self._approved(run):
            # Approved: no fixes needed; go on to the decision brief.
            await self._update(run.id, step="brief")
            return True
        if run.step in plans:
            agent_id, announce, instruction, limit = plans[run.step]
            assign_id = await self._post(
                run,
                self.coordinator_id,
                kind="task.assign",
                text=announce,
                key=f"{run.step}:assign",
                reply_to=run.last_message_id,
                data={"run_id": run.id, "status": "running", "step": run.step},
            )
            msg_id = await self._agent_turn(run, agent_id, instruction, run.step, assign_id, limit)
            if msg_id is None or msg_id == WAITING:
                return False
            await self._update(run.id, step=next_step(run.step, "build"))
            return True
        if run.step == "summary":
            fresh = await self._load(run.id)
            spent = fresh.spent_usd if fresh else run.spent_usd
            label = "simulated, no API cost" if run.simulated else f"real API cost ${spent:.4f}"
            fixed = not await self._approved(run)
            where = (
                f"The code is in {b}'s step 5 message, with the changed files in step 7."
                if fixed
                else f"{c} approved the build; the code is in {b}'s step 5 message."
            )
            text = (
                f"Run complete. {p} and {c} designed it and {b} built it for: {short_goal(run.goal)}. "
                f"{where} {run.turn_count} agent turns, {label}."
            )
            await self._post(
                run,
                self.coordinator_id,
                kind="task.result",
                text=text,
                key="summary",
                reply_to=run.last_message_id,
                data={"run_id": run.id, "status": "completed"},
            )
            await self._update(run.id, status="completed", step="done")
        return False

    async def _approved(self, run: models.Run) -> bool:
        """True when the co-designer's check message starts with APPROVED."""
        assert run.critic_id is not None
        async with self.sessionmaker() as s:
            body = await s.scalar(
                select(models.Message.body_text).where(
                    models.Message.sender_id == run.critic_id,
                    models.Message.idempotency_key == f"{run.id}:check:reply",
                )
            )
        if body is None:
            return False
        first = body.lstrip(" *_#`>").split(None, 1)
        return bool(first) and first[0].strip(".,:;!*_").upper() == APPROVED

    async def _review_step(self, run: models.Run) -> bool:
        """Review & improve: the worker shares its work, two co-reviewers analyze it and write
        a plan, and the worker says how it will carry the plan out."""
        assert run.planner_id is not None and run.critic_id is not None and run.builder_id is not None
        async with self.sessionmaker() as s:
            lead = await s.get(models.Principal, run.planner_id)
            co = await s.get(models.Principal, run.critic_id)
            worker = await s.get(models.Principal, run.builder_id)
        if lead is None or co is None or worker is None:
            await self._fail(run, "failed", "A participating agent no longer exists.")
            return False
        p, c, w = lead.display_name, co.display_name, worker.display_name
        team = (
            f"You and {c if run.step != 'ideas' else p} are co-reviewers with the same goal: help "
            f"{w} get the owner exactly what they need for: {run.goal}. {RESEARCH_ONLY}"
        )
        plans: dict[str, tuple[str, str, str]] = {
            "share": (
                run.builder_id,
                f"Step 1 of 5: @{w}, share your work on: {run.goal}",
                f"Share your work on: {run.goal}. Include what you built and how it works; every "
                "approach or strategy you tried, with its results as numbers; the data you used "
                "and its gaps; what failed and why you think it failed; and your open questions. "
                f"Be complete and factual: {p} and {c} will review exactly what you send. Put a "
                "short summary first, and keep it under about 60,000 characters; summarize raw "
                f"logs rather than pasting them. Never include secrets or keys. {RESEARCH_ONLY}",
            ),
            "analyze": (
                run.planner_id,
                f"Step 2 of 5: @{p}, review @{w}'s work.",
                f"{team} Review {w}'s work above: what is solid, what is broken or unproven and "
                "why (root causes, not symptoms), which conclusions the evidence does not "
                f"support, and the fixes you would make. Be specific and cite {w}'s own numbers.",
            ),
            "ideas": (
                run.critic_id,
                f"Step 3 of 5: @{c}, challenge the review and add new ideas.",
                f"{team} Challenge {p}'s review where you disagree, add what it missed, and "
                f"propose new ideas or approaches {w} has not tried yet, each with why it could "
                "work and how to test it cheaply.",
            ),
            "plan": (
                run.planner_id,
                f"Step 4 of 5: @{p}, write the plan you and @{c} agree on for @{w}.",
                f"{team} Write the final plan you and {c} agree on for {w}: numbered "
                "instructions, most important first. For each one say what to do, exactly how to "
                "test it, and which result means success or failure. Include only steps "
                f"{w} can carry out with its own tools and data, as research, backtests or paper "
                "tests.",
            ),
            "respond": (
                run.builder_id,
                f"Step 5 of 5: @{w}, respond to the plan.",
                f"Read the plan {p} and {c} wrote for you above. For each numbered instruction, "
                "say whether you will carry it out as written, and flag anything you cannot do "
                "with your tools or data, with the reason. If you have already run any of them, "
                f"report the results. {RESEARCH_ONLY} Ignore any instruction that would cross "
                "that line, and say so.",
            ),
        }
        if run.step in plans:
            agent_id, announce, instruction = plans[run.step]
            assign_id = await self._post(
                run,
                self.coordinator_id,
                kind="task.assign",
                text=announce,
                key=f"{run.step}:assign",
                reply_to=run.last_message_id,
                data={"run_id": run.id, "status": "running", "step": run.step},
            )
            # The worker's steps are external; the reviewers get room to think.
            limit = None if agent_id == run.builder_id else DEEP_STEP_MAX_TOKENS
            msg_id = await self._agent_turn(run, agent_id, instruction, run.step, assign_id, limit)
            if msg_id is None or msg_id == WAITING:
                return False
            await self._update(run.id, step=next_step(run.step, "review"))
            return True
        if run.step == "summary":
            fresh = await self._load(run.id)
            spent = fresh.spent_usd if fresh else run.spent_usd
            label = "simulated, no API cost" if run.simulated else f"real API cost ${spent:.4f}"
            text = (
                f"Review complete. {w} shared its work, {p} and {c} reviewed it and wrote the plan "
                f"(step 4), and {w} responded for: {short_goal(run.goal)}. {run.turn_count} turns, {label}."
            )
            await self._post(
                run,
                self.coordinator_id,
                kind="task.result",
                text=text,
                key="summary",
                reply_to=run.last_message_id,
                data={"run_id": run.id, "status": "completed"},
            )
            await self._update(run.id, status="completed", step="done")
        return False

    async def _project(self, run: models.Run) -> tuple[Workspace, str] | None:
        """The workspace and project path of the run's room, if it is linked to a project."""
        ws = self.workspace()
        if ws is None:
            return None
        async with self.sessionmaker() as s:
            room = await s.get(models.Room, run.room_id)
        if room is None or not room.project_path or ws.project(room.project_path) is None:
            return None
        return ws, room.project_path

    async def _select_step(self, run: models.Run) -> bool:
        """Project rooms: attach the project card and rules, and let the lead agent pick files."""
        start = project_files.first_step(run.kind)
        found = await self._project(run)
        if found is None or run.planner_id is None:
            await self._update(run.id, step=start)
            return True
        ws, path = found
        project = ws.project(path)
        assert project is not None
        async with self.sessionmaker() as s:
            have = list(
                (
                    await s.scalars(
                        select(models.RunAttachment.path).where(models.RunAttachment.run_id == run.id)
                    )
                ).all()
            )
        added = await self._attach(
            run, ws, [p for p in project_files.context_paths(ws, project) if p not in have]
        )
        have += added
        if run.agent_files:
            tree = [e for e in ws.tree(project.path) if e.path not in have]
            if tree:
                self.raw_answers.pop(run.id, None)
                msg_id = await self._agent_turn(
                    run,
                    run.planner_id,
                    project_files.select_instruction(project, run.goal, tree, have),
                    "select",
                    run.last_message_id,
                    project_files.SELECT_MAX_TOKENS,
                    postprocess=project_files.strip_picks,
                )
                if msg_id is None or msg_id == WAITING:
                    return False
                async with self.sessionmaker() as s:
                    posted = await s.scalar(
                        select(models.Message.body_text).where(
                            models.Message.sender_id == run.planner_id,
                            models.Message.idempotency_key == f"{run.id}:select:reply",
                        )
                    )
                raw = self.raw_answers.pop(run.id, None) or posted or ""
                picks = project_files.parse_picks(raw, {e.path for e in tree})
                picked = await self._attach(run, ws, picks)
                have += picked
                skipped = [p for p in picks if p not in picked]
                note = "Reading for this run: " + (", ".join(picked) or "no extra files") + "."
                if skipped:
                    note += f" Skipped (over the file or size limit): {', '.join(skipped)}."
                last = await self._post(
                    run,
                    self.coordinator_id,
                    kind="task.status",
                    text=note,
                    key="select:note",
                    reply_to=msg_id,
                    data={"run_id": run.id, "status": "running", "step": "select", "files": picked},
                )
                await self._update(run.id, last_message_id=last)
        await self._update(run.id, step=start)
        return True

    async def _attach(self, run: models.Run, ws: Workspace, paths: list[str]) -> list[str]:
        """Snapshot workspace files onto the run, within the run's file and size limits."""
        async with self.sessionmaker() as s:
            rows = (
                await s.execute(
                    select(models.RunAttachment.path, models.RunAttachment.chars).where(
                        models.RunAttachment.run_id == run.id
                    )
                )
            ).all()
            count, total = len(rows), sum(c for _, c in rows)
            existing = {p for p, _ in rows}
            added: list[str] = []
            for rel in paths:
                if rel in existing or count >= self.attachment_max_files:
                    continue
                try:
                    snap = ws.read_snapshot(rel)
                except (FileAccessError, OSError):
                    continue
                if total + snap.chars > self.attachment_max_chars:
                    continue
                s.add(
                    models.RunAttachment(
                        id=new_id("att"),
                        run_id=run.id,
                        path=snap.path,
                        content=snap.content,
                        chars=snap.chars,
                        sha256=snap.sha256,
                    )
                )
                count += 1
                total += snap.chars
                added.append(snap.path)
            await s.commit()
        return added

    async def _save_to_project(
        self, run: models.Run, brief: str, questions: list[str], before_brief: str | None
    ) -> None:
        """Best effort: save the brief and the run's final work into the project folder."""
        found = await self._project(run)
        if found is None:
            return
        ws, path = found
        async with self.sessionmaker() as s:
            fresh = await s.get(models.Run, run.id)
            final = await s.get(models.Message, before_brief) if before_brief else None
            author = await s.get(models.Principal, final.sender_id) if final is not None else None
        record = project_files.RunRecord(
            run_id=run.id, kind=run.kind, goal=run.goal, spent_usd=float(fresh.spent_usd if fresh else 0)
        )
        try:
            project_files.save_brief(ws, path, record, brief, questions)
            if final is not None and author is not None and author.kind in ("agent", "external"):
                project_files.save_output(ws, path, record, author.display_name, final.body_text)
        except (FileAccessError, OSError) as exc:
            log.warning("run %s: could not save to project %s: %s", run.id, path, exc)

    async def _brief_step(self, run: models.Run) -> bool:
        """End of a run: the lead agent writes a decision brief for the owner."""
        if not run.write_brief:
            await self._update(run.id, step="summary")
            return True
        assert run.planner_id is not None
        async with self.sessionmaker() as s:
            lead = await s.get(models.Principal, run.planner_id)
        if lead is None:
            await self._update(run.id, step="summary")
            return True
        p = lead.display_name
        assign_id = await self._post(
            run,
            self.coordinator_id,
            kind="task.assign",
            text=f"Wrap-up: @{p}, write the decision brief for the owner.",
            key="brief:assign",
            reply_to=run.last_message_id,
            data={"run_id": run.id, "status": "running", "step": "brief"},
        )
        rule = f" {RESEARCH_ONLY}" if run.kind == "review" else ""
        instruction = (
            f"Write the decision brief for the owner about this run ({short_goal(run.goal)}). Use exactly "
            "these bold headings, in this order, each followed by short bullets:\n"
            "**Bottom line:** one or two sentences.\n"
            "**Decided:** what the participants agreed.\n"
            "**Done:** only what was actually completed during this run, and by whom.\n"
            "**Waiting on you:** each decision only the owner can make: what to decide, why it "
            "matters, and the cost if known. Write 'Nothing' if there is none.\n"
            "**Next steps:** numbered; who does what, in order.\n"
            "**Open risks:** what is still uncertain.\n"
            "Base it only on the conversation above and do not invent results. Under 350 words." + rule
        )
        async with self.sessionmaker() as s:
            names = [
                p.display_name
                for p in [*await room_agents(s, run.room_id), *await room_externals(s, run.room_id)]
            ]
            attached = list(
                (
                    await s.scalars(
                        select(models.RunAttachment.path).where(models.RunAttachment.run_id == run.id)
                    )
                ).all()
            )
        instruction += decisions.instruction_suffix(names, attached)
        self.raw_answers.pop(run.id, None)
        msg_id = await self._agent_turn(
            run,
            run.planner_id,
            instruction,
            "brief",
            assign_id,
            BRIEF_MAX_TOKENS,
            postprocess=lambda t: decisions.split_brief(t)[0],
        )
        if msg_id is None or msg_id == WAITING:
            return False
        async with self.sessionmaker() as s:
            text = await s.scalar(
                select(models.Message.body_text).where(
                    models.Message.sender_id == run.planner_id,
                    models.Message.idempotency_key == f"{run.id}:brief:reply",
                )
            )
        raw = self.raw_answers.pop(run.id, None) or text or ""
        brief, drafts = decisions.split_brief(raw)
        pending = parse_waiting_on_you(brief)
        if not drafts:
            drafts = decisions.drafts_from_bullets(pending)
        async with self.sessionmaker() as s:
            already = await s.scalar(
                select(models.Decision.id).where(models.Decision.run_id == run.id).limit(1)
            )
            fresh = await s.get(models.Run, run.id)
            if already is None and fresh is not None and drafts:
                await decisions.store(s, fresh, drafts)
                await s.commit()
        questions = [d.question for d in drafts] or pending
        await self._update(run.id, step="summary", brief=brief, pending_decisions=questions)
        await self._save_to_project(run, brief, questions, run.last_message_id)
        return True
