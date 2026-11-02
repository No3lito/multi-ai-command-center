"""Coordinator: the replaceable orchestration engine interface and the built-in engine.

Engines never call providers or the database directly for side effects that matter: model
calls go through ModelPort (budget reservation), and messages go through the messaging
service (ordering, idempotency). Each step posts with a deterministic idempotency key, so a
step re-run after a crash never duplicates a message.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from command_center.db import models
from command_center.ids import new_id
from command_center.messaging import service
from command_center.orchestrator.context import build_request
from command_center.providers.base import ProviderError
from command_center.providers.model_port import BudgetExceeded, ModelPort, ProviderNotReady

log = logging.getLogger(__name__)

MAX_REPLY_HOPS = 3
MAX_MENTIONS_PER_MESSAGE = 5
DEFAULT_MAX_RUNS_PER_TREE = 10
COLLAB_STEPS = ("plan", "critique", "revise", "summary")
FINISHED = {"completed", "failed", "cancelled", "budget_exceeded"}


class OrchestrationEngine(Protocol):
    """Replaceable engine (LangGraph or Microsoft Agent Framework are evaluated in Phase 3)."""

    name: str

    async def step(self, run_id: str) -> bool:
        """Advance the run by one step. Returns True while the run still has work left."""
        ...


def next_step(step: str) -> str:
    i = COLLAB_STEPS.index(step)
    return COLLAB_STEPS[i + 1] if i + 1 < len(COLLAB_STEPS) else "done"


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
    ) -> None:
        self.max_runs_per_tree = max_runs_per_tree
        self.sessionmaker = sessionmaker
        self.models = models_port
        self.coordinator_id = coordinator_id
        self.reply_budget_usd = reply_budget_usd
        self.simulated = simulated

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
        async with self.sessionmaker() as s:
            sender = await s.get(models.Principal, sender_id)
            assert sender is not None
            result = await service.append_message(
                s,
                run.room_id,
                sender,
                kind=kind,
                text=text,
                idempotency_key=f"{run.id}:{key}",
                reply_to=reply_to,
                mentions=mentions,
                data=data,
                usage=usage,
                correlation_id=run.id,
            )
            return result.message.id

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

    # ------------------------------------------------------------ agent turn

    async def _agent_turn(
        self, run: models.Run, agent_id: str, instruction: str, step_key: str, reply_to: str | None
    ) -> str | None:
        """One model call plus the agent's message. Returns the message id, or None if the run ended."""
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
            if agent is None or profile is None:
                await self._fail(run, "failed", "Agent no longer exists.")
                return None
            req = await build_request(
                s, room_id=run.room_id, agent=agent, profile=profile, instruction=instruction
            )
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
        text = result.response.text.strip() or "(empty response)"
        if result.response.truncated:
            text += (
                f"\n\n[Cut off: this answer reached {name}'s output limit of "
                f"{profile.max_output_tokens} tokens.]"
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
        if msg_id is not None:
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
            msg_id = await self._agent_turn(run, agent_id, instruction, run.step, assign_id)
            if msg_id is None:
                return False
            await self._update(run.id, step=next_step(run.step))
            return True
        if run.step == "summary":
            fresh = await self._load(run.id)
            spent = fresh.spent_usd if fresh else run.spent_usd
            label = "simulated, no API cost" if run.simulated else f"real API cost ${spent:.4f}"
            text = (
                f"Run complete. {p} planned, {c} reviewed, and {p} produced the revised plan above "
                f"for: {run.goal}. {run.turn_count} agent turns, {label}."
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
