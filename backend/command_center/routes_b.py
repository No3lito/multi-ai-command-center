"""Milestone B routes and seeding: agents, room membership, runs, usage, mention routing."""

from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Query, Request
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from command_center.config import Settings
from command_center.db import models
from command_center.db.session import Database
from command_center.ids import new_id
from command_center.messaging import service
from command_center.orchestrator.engine import create_reply_runs, room_agents
from command_center.protocol import (
    AgentIn,
    AgentOut,
    AgentPatch,
    MemberIn,
    PriceOut,
    RoomDetailOut,
    RunCreateIn,
    RunOut,
    UsageOut,
    UsageRow,
)
from command_center.providers.model_port import LIVE_SCOPE, agent_status
from command_center.providers.prices import price_for

DEFAULT_REPLY_BUDGET = Decimal("0.25")

CLAUDE_PROMPT = (
    "You lead planning. Turn goals into clear, ordered, testable steps, and say what you would "
    "verify. When reviewing others, be specific and kind."
)
GPT_PROMPT = (
    "You lead review. Find gaps, risks and simpler alternatives, and suggest concrete fixes. "
    "When asked to plan, keep plans short and practical."
)


async def seed(db: Database, settings: Settings) -> str:
    """Create the Coordinator and, on first start, the Claude and GPT agents. Returns the coordinator id."""
    async with db.sessionmaker() as s:
        coordinator = await s.scalar(
            select(models.Principal).where(
                models.Principal.kind == "system", models.Principal.display_name == "Coordinator"
            )
        )
        if coordinator is None:
            coordinator = models.Principal(id=new_id("sys"), kind="system", display_name="Coordinator")
            s.add(coordinator)
            await s.flush()
        has_agents = await s.scalar(select(models.AgentProfile.principal_id).limit(1))
        if has_agents is None:
            general = await s.scalar(select(models.Room).where(models.Room.name == "General"))
            for name, role, provider, model, prompt in (
                ("Claude", "Planner", "anthropic", settings.default_claude_model, CLAUDE_PROMPT),
                ("GPT", "Reviewer", "openai", settings.default_openai_model, GPT_PROMPT),
            ):
                agent = models.Principal(id=new_id("agt"), kind="agent", display_name=name)
                s.add(agent)
                await s.flush()
                s.add(
                    models.AgentProfile(
                        principal_id=agent.id,
                        role=role,
                        provider=provider,
                        model=model,
                        system_prompt=prompt,
                        max_output_tokens=1024,
                        enabled=True,
                    )
                )
                if general is not None:
                    s.add(models.RoomMember(room_id=general.id, principal_id=agent.id))
        await s.commit()
        return coordinator.id


def agent_out(settings: Settings, p: models.Principal, a: models.AgentProfile) -> AgentOut:
    price = price_for(a.provider, a.model)
    return AgentOut(
        id=p.id,
        display_name=p.display_name,
        role=a.role,
        provider=a.provider,
        model=a.model,
        system_prompt=a.system_prompt,
        max_output_tokens=a.max_output_tokens,
        enabled=a.enabled,
        status=agent_status(settings, a),
        price=PriceOut(input_per_mtok=float(price.input), output_per_mtok=float(price.output))
        if price
        else None,
    )


def run_out(r: models.Run) -> RunOut:
    return RunOut(
        id=r.id,
        room_id=r.room_id,
        kind=r.kind,
        status=r.status,
        goal=r.goal,
        step=r.step,
        planner_id=r.planner_id,
        critic_id=r.critic_id,
        agent_id=r.agent_id,
        turn_count=r.turn_count,
        max_turns=r.max_turns,
        budget_usd=float(r.budget_usd),
        spent_usd=float(r.spent_usd),
        simulated=r.simulated,
        error=r.error,
        created_at=r.created_at,
        updated_at=r.updated_at,
        finished_at=r.finished_at,
    )


def register(
    app: FastAPI,
    *,
    settings: Settings,
    get_session: Callable[[], Any],
    current_principal: Callable[..., Awaitable[models.Principal]],
    member_room: Callable[[AsyncSession, str, models.Principal], Awaitable[models.Room]],
    api_error: Callable[[int, str, str], Exception],
    audit: Callable[..., Awaitable[None]],
) -> None:
    SessionDep = Annotated[AsyncSession, Depends(get_session)]
    PrincipalDep = Annotated[models.Principal, Depends(current_principal)]

    def wake() -> None:
        worker = getattr(app.state, "worker", None)
        if worker is not None:
            worker.wake()

    def require_owner(p: models.Principal) -> None:
        if p.kind != "owner":
            raise api_error(403, "forbidden", "Only the owner can do this")

    # ------------------------------------------------------------ agents

    @app.get("/api/agents", response_model=list[AgentOut])
    async def list_agents(principal: PrincipalDep, session: SessionDep) -> list[AgentOut]:
        rows = (
            await session.execute(
                select(models.Principal, models.AgentProfile)
                .join(models.AgentProfile, models.AgentProfile.principal_id == models.Principal.id)
                .order_by(models.Principal.display_name)
            )
        ).all()
        return [agent_out(settings, p, a) for p, a in rows]

    async def name_taken(session: AsyncSession, name: str, exclude: str | None = None) -> bool:
        stmt = select(models.Principal.id).where(
            func.lower(models.Principal.display_name) == name.lower(), models.Principal.kind == "agent"
        )
        if exclude:
            stmt = stmt.where(models.Principal.id != exclude)
        return await session.scalar(stmt) is not None

    @app.post("/api/agents", response_model=AgentOut, status_code=201)
    async def create_agent(
        body: AgentIn, request: Request, principal: PrincipalDep, session: SessionDep
    ) -> AgentOut:
        require_owner(principal)
        if await name_taken(session, body.display_name):
            raise api_error(409, "agent_exists", "An agent with that name already exists")
        p = models.Principal(id=new_id("agt"), kind="agent", display_name=body.display_name)
        session.add(p)
        await session.flush()
        a = models.AgentProfile(
            principal_id=p.id,
            role=body.role,
            provider=body.provider,
            model=body.model,
            system_prompt=body.system_prompt,
            max_output_tokens=body.max_output_tokens,
            enabled=body.enabled,
        )
        session.add(a)
        await session.commit()
        await audit(session, "agent.create", principal.id, p.id, request, provider=a.provider, model=a.model)
        return agent_out(settings, p, a)

    @app.patch("/api/agents/{agent_id}", response_model=AgentOut)
    async def update_agent(
        agent_id: str, body: AgentPatch, request: Request, principal: PrincipalDep, session: SessionDep
    ) -> AgentOut:
        require_owner(principal)
        p = await session.get(models.Principal, agent_id)
        a = await session.get(models.AgentProfile, agent_id)
        if p is None or a is None:
            raise api_error(404, "agent_not_found", "Agent not found")
        changes = body.model_dump(exclude_unset=True)
        if "display_name" in changes:
            if await name_taken(session, changes["display_name"], exclude=agent_id):
                raise api_error(409, "agent_exists", "An agent with that name already exists")
            p.display_name = changes.pop("display_name")
        for key, value in changes.items():
            setattr(a, key, value)
        await session.commit()
        await audit(
            session,
            "agent.update",
            principal.id,
            agent_id,
            request,
            fields=sorted(body.model_dump(exclude_unset=True)),
        )
        return agent_out(settings, p, a)

    @app.post("/api/rooms/{room_id}/members", response_model=RoomDetailOut)
    async def add_member(
        room_id: str, body: MemberIn, principal: PrincipalDep, session: SessionDep
    ) -> RoomDetailOut:
        room = await member_room(session, room_id, principal)
        agent = await session.get(models.Principal, body.principal_id)
        if agent is None or agent.kind != "agent":
            raise api_error(422, "validation_error", "principal_id: only agents can be added to rooms")
        if await session.get(models.RoomMember, (room_id, agent.id)) is None:
            session.add(models.RoomMember(room_id=room_id, principal_id=agent.id))
            await session.commit()
        members = await service.room_members(session, room.id)
        return RoomDetailOut(
            id=room.id,
            name=room.name,
            created_at=room.created_at,
            member_count=len(members),
            last_seq=room.last_seq,
            members=members,
        )

    # ------------------------------------------------------------ runs

    @app.post("/api/rooms/{room_id}/runs", response_model=RunOut, status_code=201)
    async def create_run(
        room_id: str, body: RunCreateIn, request: Request, principal: PrincipalDep, session: SessionDep
    ) -> RunOut:
        await member_room(session, room_id, principal)
        if body.planner_id == body.critic_id:
            raise api_error(422, "validation_error", "Planner and critic must be different agents")
        agents = {a.id for a in await room_agents(session, room_id)}
        for role, agent_id in (("planner", body.planner_id), ("critic", body.critic_id)):
            if agent_id not in agents:
                raise api_error(422, "validation_error", f"{role}_id: not an enabled agent in this room")
        run = models.Run(
            id=new_id("run"),
            room_id=room_id,
            kind="collab",
            status="queued",
            step="plan",
            goal=body.goal.strip(),
            planner_id=body.planner_id,
            critic_id=body.critic_id,
            max_turns=body.max_turns,
            budget_usd=Decimal(str(body.budget_usd)),
            spent_usd=Decimal(0),
            simulated=settings.provider_mode == "simulated",
            created_by=principal.id,
        )
        session.add(run)
        await session.commit()
        await audit(session, "run.create", principal.id, run.id, request, budget_usd=body.budget_usd)
        wake()
        return run_out(run)

    @app.get("/api/rooms/{room_id}/runs", response_model=list[RunOut])
    async def list_runs(
        room_id: str,
        principal: PrincipalDep,
        session: SessionDep,
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
    ) -> list[RunOut]:
        await member_room(session, room_id, principal)
        rows = await session.scalars(
            select(models.Run)
            .where(models.Run.room_id == room_id)
            .order_by(models.Run.created_at.desc())
            .limit(limit)
        )
        return [run_out(r) for r in rows]

    async def own_run(session: AsyncSession, run_id: str, principal: models.Principal) -> models.Run:
        run = await session.get(models.Run, run_id)
        if run is None:
            raise api_error(404, "run_not_found", "Run not found")
        await member_room(session, run.room_id, principal)
        return run

    @app.get("/api/runs/{run_id}", response_model=RunOut)
    async def get_run(run_id: str, principal: PrincipalDep, session: SessionDep) -> RunOut:
        return run_out(await own_run(session, run_id, principal))

    @app.post("/api/runs/{run_id}/cancel", response_model=RunOut)
    async def cancel_run(
        run_id: str, request: Request, principal: PrincipalDep, session: SessionDep
    ) -> RunOut:
        run = await own_run(session, run_id, principal)
        if run.status in ("queued", "running"):
            run.status = "cancelled"
            run.finished_at = func.now()
            await session.commit()
            await session.refresh(run)
            await audit(session, "run.cancel", principal.id, run.id, request)
        return run_out(run)

    # ------------------------------------------------------------ usage

    @app.get("/api/usage", response_model=UsageOut)
    async def usage(principal: PrincipalDep, session: SessionDep) -> UsageOut:
        cap = await session.get(models.SpendCap, LIVE_SCOPE)
        u = models.UsageEntry
        rows = (
            await session.execute(
                select(
                    u.provider,
                    u.model,
                    u.simulated,
                    func.count(),
                    func.sum(u.input_tokens),
                    func.sum(u.output_tokens),
                    func.sum(u.cost_usd),
                )
                .group_by(u.provider, u.model, u.simulated)
                .order_by(case((u.simulated.is_(True), 1), else_=0), u.provider, u.model)
            )
        ).all()
        by_provider = [
            UsageRow(
                provider=prov,
                model=model,
                calls=calls,
                input_tokens=int(tin or 0),
                output_tokens=int(tout or 0),
                cost_usd=float(cost or 0),
                simulated=sim,
            )
            for prov, model, sim, calls, tin, tout, cost in rows
        ]
        cap_usd = float(cap.cap_usd) if cap else settings.live_budget_usd
        spent = float(cap.spent_usd) if cap else 0.0
        reserved = float(cap.reserved_usd) if cap else 0.0
        return UsageOut(
            cap_usd=cap_usd,
            spent_usd=spent,
            reserved_usd=reserved,
            remaining_usd=max(cap_usd - spent - reserved, 0.0),
            by_provider=by_provider,
            simulated_calls=sum(r.calls for r in by_provider if r.simulated),
        )


async def route_mentions(
    app: FastAPI,
    settings: Settings,
    session: AsyncSession,
    room_id: str,
    message_id: str,
    mentions: list[str],
    sender: models.Principal,
) -> None:
    """Human chat that mentions agents creates one reply run per mentioned agent."""
    if not mentions or sender.kind not in ("owner", "human"):
        return
    msg = await session.get(models.Message, message_id)
    runs = await create_reply_runs(
        session,
        room_id=room_id,
        trigger=msg,
        trigger_id=message_id,
        agent_ids=mentions,
        created_by=sender.id,
        hop=1,
        budget_usd=DEFAULT_REPLY_BUDGET,
        simulated=settings.provider_mode == "simulated",
    )
    if runs and getattr(app.state, "worker", None) is not None:
        app.state.worker.wake()
