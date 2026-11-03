"""Milestone B routes and seeding: agents, room membership, runs, usage, mention routing."""

import re
from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Query, Request
from sqlalchemy import case, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from command_center import decisions as decisions_mod
from command_center import files, project_files
from command_center.config import Settings
from command_center.db import models
from command_center.db.session import Database
from command_center.external import issue_token, revoke_tokens
from command_center.files import FileAccessError
from command_center.ids import new_id
from command_center.messaging import service
from command_center.orchestrator.engine import create_reply_runs, room_agents, room_externals
from command_center.protocol import (
    AgentIn,
    AgentOut,
    AgentPatch,
    AttachmentOut,
    ConnectionIn,
    ConnectionOut,
    ConnectionRoom,
    DecisionAnswerIn,
    DecisionAnswerOut,
    DecisionOut,
    FileEntryOut,
    FilesOut,
    FileSuggestionsOut,
    FollowUpPlanOut,
    HistoryOut,
    InboxFileIn,
    InboxItemOut,
    MemberIn,
    NewProjectIn,
    PriceOut,
    ProjectOut,
    RoomDetailOut,
    RoomProjectIn,
    RunCreateIn,
    RunOut,
    SuggestedFileOut,
    UsageOut,
    UsageRow,
    WorkspaceOut,
)
from command_center.providers.model_port import LIVE_SCOPE, agent_status
from command_center.providers.prices import price_for
from command_center.workspace import Project, Workspace, is_project_workspace, open_workspace

DEFAULT_REPLY_BUDGET = Decimal("0.25")  # per reply run
REPLY_TREE_BUDGET = Decimal("0.50")  # shared by every run triggered from one human message

CLAUDE_PROMPT = (
    "You are a co-designer. You and your fellow designer share one goal: give the owner exactly "
    "what they need. Turn goals into clear, concrete, buildable designs and say how to verify "
    "them. When a builder implements your design, give precise instructions, down to the code "
    "where it matters."
)
GROK_PROMPT = (
    "You are the builder. The co-designers (Claude and GPT) direct the work, and you follow "
    "their design and instructions exactly, including code-level choices. Write complete, "
    "working code. Your own input is minor: briefly flag only what would block or complicate "
    "the build."
)
GPT_PROMPT = (
    "You are a co-designer. You and your fellow designer share one goal: give the owner exactly "
    "what they need. As an equal partner, find gaps, risks and simpler options and fold them "
    "into the design. When a builder implements it, check the result and give precise fix "
    "instructions."
)


async def seed(db: Database, settings: Settings) -> str:
    """Create the Coordinator and the default agents (Claude and GPT on first start, Grok once).

    Returns the coordinator id.
    """
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
        general = await s.scalar(select(models.Room).where(models.Room.name == "General"))
        has_agents = await s.scalar(select(models.AgentProfile.principal_id).limit(1))
        defaults: list[tuple[str, str, str, str, str]] = []
        if has_agents is None:
            defaults += [
                ("Claude", "Co-designer", "anthropic", settings.default_claude_model, CLAUDE_PROMPT),
                ("GPT", "Co-designer", "openai", settings.default_openai_model, GPT_PROMPT),
            ]
        # Grok arrived after the first agents, so existing installs get it once, too.
        has_grok = await s.scalar(
            select(models.AgentProfile.principal_id).where(models.AgentProfile.provider == "xai").limit(1)
        )
        grok_name_taken = await s.scalar(
            select(models.Principal.id).where(func.lower(models.Principal.display_name) == "grok").limit(1)
        )
        if has_grok is None and grok_name_taken is None:
            defaults.append(("Grok", "Builder", "xai", settings.default_grok_model, GROK_PROMPT))
        for name, role, provider, model, prompt in defaults:
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
                    max_output_tokens=8000,
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


def run_out(r: models.Run, attachments: list[AttachmentOut] | None = None) -> RunOut:
    return RunOut(
        attachments=attachments or [],
        write_brief=r.write_brief if r.write_brief is not None else True,
        brief=r.brief,
        pending_decisions=r.pending_decisions,
        archived_at=r.archived_at,
        agent_files=r.agent_files if r.agent_files is not None else True,
        id=r.id,
        room_id=r.room_id,
        kind=r.kind,
        status=r.status,
        goal=r.goal,
        step=r.step,
        planner_id=r.planner_id,
        critic_id=r.critic_id,
        builder_id=r.builder_id,
        agent_id=r.agent_id,
        root_run_id=r.root_run_id,
        waiting_for=r.waiting_for,
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


def suggest_project(filename: str, projects: list[Project]) -> str | None:
    """A free, keyword-based guess at which project an inbox file belongs to (no AI call)."""
    words = {w for w in re.split(r"[^a-z0-9]+", filename.lower()) if len(w) >= 3}
    best, score = None, 0
    for p in projects:
        keys = {w for w in re.split(r"[^a-z0-9]+", f"{p.slug} {p.title} {p.family}".lower()) if len(w) >= 3}
        hits = len(words & keys)
        if hits > score:
            best, score = p.path, hits
    return best


def _plan(raw: Any) -> FollowUpPlanOut:
    raw = raw if isinstance(raw, dict) else {}
    return FollowUpPlanOut(
        workflow=str(raw.get("workflow") or "none"),
        worker=raw.get("worker") or None,
        goal=str(raw.get("goal") or ""),
    )


def decision_out(d: models.Decision, run_goal: str) -> DecisionOut:
    follow = d.follow_up or {}
    more = dict(follow.get("on_more_info") or {})
    more.setdefault("workflow", "collab")
    return DecisionOut(
        id=d.id,
        room_id=d.room_id,
        run_id=d.run_id,
        run_goal=run_goal.split("\n")[0][:300],
        question=d.question,
        recommendation=d.recommendation,
        recommended=d.recommended,
        why=d.why,
        suggested_note=d.suggested_note,
        cost=d.cost,
        on_approve=_plan(follow.get("on_approve")),
        on_more_info=_plan(more),
        status=d.status,
        owner_note=d.owner_note,
        decided_at=d.decided_at,
        follow_up_run_id=d.follow_up_run_id,
        created_at=d.created_at,
    )


ANSWER_STATUS = {
    "approve": "approved",
    "decline": "declined",
    "more_info": "more_info",
    "dismiss": "dismissed",
}
ANSWER_WORDS = {
    "approve": "APPROVED",
    "decline": "DECLINED",
    "more_info": "asked for MORE INFORMATION on",
    "dismiss": "dismissed (no longer relevant)",
}


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
        # null means "leave unchanged" (every field is non-nullable in the database).
        changes = body.model_dump(exclude_unset=True, exclude_none=True)
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
            fields=sorted(body.model_dump(exclude_unset=True, exclude_none=True)),
        )
        return agent_out(settings, p, a)

    @app.post("/api/rooms/{room_id}/members", response_model=RoomDetailOut)
    async def add_member(
        room_id: str, body: MemberIn, principal: PrincipalDep, session: SessionDep
    ) -> RoomDetailOut:
        room = await member_room(session, room_id, principal)
        agent = await session.get(models.Principal, body.principal_id)
        if agent is None or agent.kind not in ("agent", "external"):
            raise api_error(
                422, "validation_error", "principal_id: only agents and connections can be added to rooms"
            )
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
            project_path=room.project_path,
            members=members,
        )

    # ------------------------------------------------------------ runs

    @app.post("/api/rooms/{room_id}/runs", response_model=RunOut, status_code=201)
    async def create_run(
        room_id: str, body: RunCreateIn, request: Request, principal: PrincipalDep, session: SessionDep
    ) -> RunOut:
        room = await member_room(session, room_id, principal)
        # Project rooms start with a "select" step: project card attached, lead agent picks files.
        project_room = bool(room.project_path) and is_project_workspace(
            open_workspace(settings.files_root, settings.sources_root)
        )
        build = body.workflow == "build"
        review = body.workflow == "review"
        roles = [("planner", body.planner_id), ("critic", body.critic_id)]
        if build or review:
            if body.builder_id is None:
                raise api_error(
                    422, "validation_error", f"builder_id is required for the {body.workflow} workflow"
                )
            roles.append(("builder", body.builder_id))
        elif body.builder_id is not None:
            raise api_error(
                422, "validation_error", "builder_id is only used by the build and review workflows"
            )
        if len({agent_id for _, agent_id in roles}) != len(roles):
            raise api_error(422, "validation_error", "Each role needs a different agent")
        agents = {a.id for a in await room_agents(session, room_id)}
        externals = {e.id for e in await room_externals(session, room_id)}
        for role, agent_id in roles:
            # External agents (Grok Bot over MCP) can be the builder or worker; the designers
            # and reviewers are model agents, since they must answer within the run.
            allowed = agents | externals if role == "builder" else agents
            if agent_id not in allowed:
                raise api_error(422, "validation_error", f"{role}_id: not an enabled agent in this room")
        # Attachments: snapshot each file now, so every step sees the same version.
        snapshots: list[files.Snapshot] = []
        wanted = list(dict.fromkeys(body.attachments))
        if wanted:
            ws = open_workspace(settings.files_root, settings.sources_root)
            if ws is None:
                raise api_error(422, "validation_error", "attachments: no shared folder is configured")
            if len(wanted) > settings.attachment_max_files:
                raise api_error(
                    422, "validation_error", f"attachments: at most {settings.attachment_max_files} files"
                )
            for rel in wanted:
                try:
                    snapshots.append(ws.read_snapshot(rel))
                except (files.FileAccessError, OSError) as exc:
                    raise api_error(422, "validation_error", f"attachments: {exc}") from exc
            total = sum(s.chars for s in snapshots)
            if total > settings.attachment_max_chars:
                raise api_error(
                    422,
                    "validation_error",
                    f"attachments: {total:,} characters in total; "
                    f"the limit is {settings.attachment_max_chars:,}",
                )
        run_id = new_id("run")
        run = models.Run(
            id=run_id,
            root_run_id=run_id,  # a collaboration is the root of its own run tree
            room_id=room_id,
            kind=body.workflow,
            status="queued",
            step="select"
            if project_room
            else {"build": "design", "review": "share"}.get(body.workflow, "plan"),
            goal=body.goal.strip(),
            planner_id=body.planner_id,
            critic_id=body.critic_id,
            builder_id=body.builder_id,
            # Agent turns needed: build 7, review 5, plan & review 3, plus one for the brief.
            max_turns=max(
                body.max_turns,
                (7 if build else 5 if review else 3)
                + (1 if body.brief else 0)
                + (1 if project_room and body.agent_files else 0),
            ),
            write_brief=body.brief,
            agent_files=body.agent_files,
            budget_usd=Decimal(str(body.budget_usd)),
            spent_usd=Decimal(0),
            simulated=settings.provider_mode == "simulated",
            created_by=principal.id,
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
        await session.commit()
        await audit(
            session,
            "run.create",
            principal.id,
            run.id,
            request,
            budget_usd=body.budget_usd,
            attachments=[s.path for s in snapshots],
        )
        wake()
        return run_out(run, [AttachmentOut(path=s.path, chars=s.chars) for s in snapshots])

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
        runs = list(rows.all())
        atts = await attachments_for(session, [r.id for r in runs])
        return [run_out(r, atts.get(r.id)) for r in runs]

    async def attachments_for(session: AsyncSession, run_ids: list[str]) -> dict[str, list[AttachmentOut]]:
        if not run_ids:
            return {}
        rows = await session.execute(
            select(models.RunAttachment.run_id, models.RunAttachment.path, models.RunAttachment.chars)
            .where(models.RunAttachment.run_id.in_(run_ids))
            .order_by(models.RunAttachment.created_at, models.RunAttachment.path)
        )
        out: dict[str, list[AttachmentOut]] = {}
        for run_id, path, chars in rows.all():
            out.setdefault(run_id, []).append(AttachmentOut(path=path, chars=chars))
        return out

    # ------------------------------------------------------------ shared files (read-only)

    @app.get("/api/files", response_model=FilesOut)
    async def list_files(principal: PrincipalDep, path: str = "") -> FilesOut:
        """Browse the shared folder (owner only) to pick files to attach to a run."""
        require_owner(principal)
        ws = open_workspace(settings.files_root, settings.sources_root)
        if ws is None:
            return FilesOut(
                enabled=False,
                path="",
                entries=[],
                max_files=settings.attachment_max_files,
                max_chars=settings.attachment_max_chars,
            )
        try:
            entries = ws.list_dir(path)
        except files.FileAccessError as exc:
            raise api_error(422, "validation_error", str(exc)) from exc
        return FilesOut(
            enabled=True,
            path=path.replace("\\", "/").strip("/"),
            entries=[
                FileEntryOut(name=e.name, path=e.path, type=e.type, size=e.size, readable=e.readable)
                for e in entries
            ],
            max_files=settings.attachment_max_files,
            max_chars=settings.attachment_max_chars,
        )

    async def own_run(session: AsyncSession, run_id: str, principal: models.Principal) -> models.Run:
        run = await session.get(models.Run, run_id)
        if run is None:
            raise api_error(404, "run_not_found", "Run not found")
        await member_room(session, run.room_id, principal)
        return run

    @app.get("/api/runs/{run_id}", response_model=RunOut)
    async def get_run(run_id: str, principal: PrincipalDep, session: SessionDep) -> RunOut:
        run = await own_run(session, run_id, principal)
        return run_out(run, (await attachments_for(session, [run.id])).get(run.id))

    @app.post("/api/runs/{run_id}/cancel", response_model=RunOut)
    async def cancel_run(
        run_id: str, request: Request, principal: PrincipalDep, session: SessionDep
    ) -> RunOut:
        """Cancels the run and every unfinished run in its tree (replies it triggered, and so on)."""
        run = await own_run(session, run_id, principal)
        root_id = run.root_run_id or run.id
        # Same lock order as budget settlement: the tree's root first, then its other runs.
        await session.execute(select(models.Run.id).where(models.Run.id == root_id).with_for_update())
        result = await session.execute(
            update(models.Run)
            .where(
                (models.Run.root_run_id == root_id) | (models.Run.id == root_id) | (models.Run.id == run.id),
                models.Run.status.in_(("queued", "running", "waiting")),
            )
            .values(
                status="cancelled",
                finished_at=func.now(),
                lease_expires_at=None,
                waiting_for=None,
                waiting_instruction=None,
            )
            .returning(models.Run.id)
        )
        cancelled = [row[0] for row in result.all()]
        await session.commit()
        await session.refresh(run)
        if cancelled:
            await audit(session, "run.cancel", principal.id, run.id, request, cancelled=cancelled)
        return run_out(run)

    # ------------------------------------------------------------ workspace and projects

    def project_out(p: Project) -> ProjectOut:
        return ProjectOut(
            path=p.path, family=p.family, slug=p.slug, title=p.title, status=p.status, goal=p.goal
        )

    def owner_workspace() -> Workspace:
        ws = open_workspace(settings.files_root, settings.sources_root)
        if not is_project_workspace(ws):
            raise api_error(422, "validation_error", "No project workspace is configured")
        assert ws is not None
        return ws

    @app.get("/api/workspace", response_model=WorkspaceOut)
    async def get_workspace(principal: PrincipalDep) -> WorkspaceOut:
        """Projects, families and inbox of the owner's workspace (owner only)."""
        require_owner(principal)
        ws = open_workspace(settings.files_root, settings.sources_root)
        if ws is None:
            return WorkspaceOut(enabled=False, structured=False, families=[], projects=[], inbox=[])
        if not is_project_workspace(ws):
            return WorkspaceOut(enabled=True, structured=False, families=[], projects=[], inbox=[])
        projects = ws.projects()
        return WorkspaceOut(
            enabled=True,
            structured=True,
            families=ws.families(),
            projects=[project_out(p) for p in projects],
            inbox=[
                InboxItemOut(name=e.name, size=e.size, suggested_project=suggest_project(e.name, projects))
                for e in ws.inbox()
            ],
        )

    @app.post("/api/workspace/projects", response_model=ProjectOut, status_code=201)
    async def create_project(
        body: NewProjectIn, request: Request, principal: PrincipalDep, session: SessionDep
    ) -> ProjectOut:
        require_owner(principal)
        ws = owner_workspace()
        try:
            project = ws.create_project(body.family, body.name, body.goal)
        except (FileAccessError, OSError) as exc:
            raise api_error(422, "validation_error", f"project: {exc}") from exc
        await audit(session, "project.create", principal.id, project.path, request)
        return project_out(project)

    @app.get("/api/rooms/{room_id}/suggest-files", response_model=FileSuggestionsOut)
    async def suggest_files(
        room_id: str,
        principal: PrincipalDep,
        session: SessionDep,
        goal: Annotated[str, Query(max_length=4000)] = "",
    ) -> FileSuggestionsOut:
        """Files in the room's project that match the goal's words (free keyword match, no AI)."""
        require_owner(principal)
        room = await member_room(session, room_id, principal)
        ws = open_workspace(settings.files_root, settings.sources_root)
        project = ws.project(room.project_path) if ws is not None and room.project_path else None
        if ws is None or project is None:
            return FileSuggestionsOut(project_path=None, always=[], suggested=[])
        hits = ws.suggest(project.path, goal)
        return FileSuggestionsOut(
            project_path=project.path,
            always=project_files.context_paths(ws, project),
            suggested=[SuggestedFileOut(path=e.path, size=e.size, matched=m) for e, _, m in hits],
        )

    @app.put("/api/rooms/{room_id}/project", response_model=RoomDetailOut)
    async def set_room_project(
        room_id: str, body: RoomProjectIn, request: Request, principal: PrincipalDep, session: SessionDep
    ) -> RoomDetailOut:
        """Link a room to a workspace project, or unlink it (project_path null)."""
        require_owner(principal)
        room = await member_room(session, room_id, principal)
        path: str | None = None
        if body.project_path:
            found = owner_workspace().project(body.project_path)
            if found is None:
                raise api_error(422, "validation_error", "project_path: not a project in the workspace")
            path = found.path
        room.project_path = path
        await session.commit()
        await audit(session, "room.project", principal.id, room.id, request, project=path)
        members = await service.room_members(session, room.id)
        return RoomDetailOut(
            id=room.id,
            name=room.name,
            created_at=room.created_at,
            member_count=len(members),
            last_seq=room.last_seq,
            project_path=room.project_path,
            members=members,
        )

    @app.post("/api/workspace/inbox/file", response_model=FileEntryOut)
    async def file_inbox_item(
        body: InboxFileIn, request: Request, principal: PrincipalDep, session: SessionDep
    ) -> FileEntryOut:
        """Move one inbox file into a project's notes/ folder. The owner's click is the approval."""
        require_owner(principal)
        ws = owner_workspace()
        try:
            path = ws.file_from_inbox(body.name, body.project_path)
        except (FileAccessError, OSError) as exc:
            raise api_error(422, "validation_error", str(exc)) from exc
        await audit(session, "inbox.file", principal.id, path, request, name=body.name)
        return FileEntryOut(name=path.rsplit("/", 1)[-1], path=path, type="file", size=None, readable=True)

    # ------------------------------------------------------------ decisions

    @app.get("/api/rooms/{room_id}/decisions", response_model=list[DecisionOut])
    async def list_decisions(
        room_id: str,
        principal: PrincipalDep,
        session: SessionDep,
        status: Annotated[str | None, Query(pattern="^(pending|decided|all)$")] = "all",
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
    ) -> list[DecisionOut]:
        """Decisions raised by this room's decision briefs: pending first, then newest decided."""
        await member_room(session, room_id, principal)
        stmt = (
            select(models.Decision, models.Run.goal)
            .join(models.Run, models.Run.id == models.Decision.run_id)
            .where(models.Decision.room_id == room_id)
        )
        if status == "pending":
            stmt = stmt.where(models.Decision.status == "pending")
        elif status == "decided":
            stmt = stmt.where(models.Decision.status != "pending")
        stmt = stmt.order_by(
            case((models.Decision.status == "pending", 0), else_=1),
            models.Decision.created_at.desc(),
            models.Decision.position,
        ).limit(limit)
        return [decision_out(d, goal) for d, goal in (await session.execute(stmt)).all()]

    @app.post("/api/decisions/{decision_id}/answer", response_model=DecisionAnswerOut)
    async def answer_decision(
        decision_id: str,
        body: DecisionAnswerIn,
        request: Request,
        principal: PrincipalDep,
        session: SessionDep,
    ) -> DecisionAnswerOut:
        """Owner answers a decision. Approve or more info starts the run the agents prepared."""
        require_owner(principal)
        decision = await session.get(models.Decision, decision_id, with_for_update=True)
        if decision is None:
            raise api_error(404, "decision_not_found", "Decision not found")
        await member_room(session, decision.room_id, principal)
        if decision.status != "pending":
            raise api_error(409, "decision_already_answered", f"This decision was already {decision.status}")
        note = (body.note or "").strip() or None
        follow_up: models.Run | None = None
        if body.answer in ("approve", "more_info"):
            try:
                follow_up = await decisions_mod.start_follow_up(
                    session,
                    settings,
                    decision,
                    answer=body.answer,
                    note=note,
                    owner_id=principal.id,
                    budget_usd=Decimal(str(body.budget_usd)) if body.budget_usd is not None else None,
                )
            except decisions_mod.FollowUpError as exc:
                raise api_error(409, "follow_up_failed", exc.message) from exc
        decision.status = ANSWER_STATUS[body.answer]
        decision.owner_note = note
        decision.decided_by = principal.id
        decision.decided_at = func.now()
        decision.follow_up_run_id = follow_up.id if follow_up is not None else None
        await session.commit()
        await session.refresh(decision)
        if follow_up is not None:
            await session.refresh(follow_up)
        source_goal = (
            await session.scalar(select(models.Run.goal).where(models.Run.id == decision.run_id)) or ""
        )
        room = await session.get(models.Room, decision.room_id)
        ws = open_workspace(settings.files_root, settings.sources_root)
        if room is not None and room.project_path and ws is not None and ws.project(room.project_path):
            try:
                project_files.save_decision(
                    ws,
                    room.project_path,
                    question=decision.question,
                    answer=ANSWER_STATUS[body.answer],
                    note=note,
                    recommendation=decision.recommendation,
                    follow_up_run_id=decision.follow_up_run_id,
                    run_id=decision.run_id,
                )
            except (FileAccessError, OSError):
                pass  # saving the record is best effort; the answer itself is stored

        # Tell the room, so every agent (Grok Bot included, via read_messages) sees the answer.
        coordinator = await session.scalar(
            select(models.Principal).where(
                models.Principal.kind == "system", models.Principal.display_name == "Coordinator"
            )
        )
        if coordinator is not None:
            text = f"Owner {ANSWER_WORDS[body.answer]}: {decision.question}"
            if note:
                text += f"\nNote: {note}"
            if follow_up is not None:
                text += f"\nStarted a {follow_up.kind} run (budget ${float(follow_up.budget_usd):.2f})."
            await service.append_message(
                session,
                decision.room_id,
                coordinator,
                kind="chat",
                text=text,
                idempotency_key=f"decision:{decision.id}",
                data={"decision_id": decision.id, "answer": body.answer},
                correlation_id=follow_up.id if follow_up is not None else decision.run_id,
            )
        await audit(
            session,
            "decision.answer",
            principal.id,
            decision.id,
            request,
            answer=body.answer,
            follow_up_run_id=decision.follow_up_run_id,
        )
        if follow_up is not None:
            wake()
        run_attachments = (
            (await attachments_for(session, [follow_up.id])).get(follow_up.id) if follow_up else None
        )
        return DecisionAnswerOut(
            decision=decision_out(decision, source_goal),
            follow_up_run=run_out(follow_up, run_attachments) if follow_up is not None else None,
        )

    # ------------------------------------------------------------ archive and history

    async def set_archived(
        run_id: str, archived: bool, request: Request, principal: models.Principal, session: AsyncSession
    ) -> RunOut:
        require_owner(principal)
        run = await own_run(session, run_id, principal)
        if run.status in ("queued", "running", "waiting"):
            raise api_error(409, "run_active", "Finish or cancel the run before archiving it")
        run.archived_at = func.now() if archived else None
        await session.commit()
        await session.refresh(run)
        await audit(session, "run.archive" if archived else "run.unarchive", principal.id, run.id, request)
        return run_out(run, (await attachments_for(session, [run.id])).get(run.id))

    @app.post("/api/runs/{run_id}/archive", response_model=RunOut)
    async def archive_run(
        run_id: str, request: Request, principal: PrincipalDep, session: SessionDep
    ) -> RunOut:
        """Hide a finished run from the chat and the run list. Nothing is deleted."""
        return await set_archived(run_id, True, request, principal, session)

    @app.post("/api/runs/{run_id}/unarchive", response_model=RunOut)
    async def unarchive_run(
        run_id: str, request: Request, principal: PrincipalDep, session: SessionDep
    ) -> RunOut:
        return await set_archived(run_id, False, request, principal, session)

    @app.get("/api/rooms/{room_id}/history", response_model=HistoryOut)
    async def room_history(
        room_id: str,
        principal: PrincipalDep,
        session: SessionDep,
        q: Annotated[str, Query(max_length=200)] = "",
        archived: Annotated[str, Query(pattern="^(include|only|exclude)$")] = "include",
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
    ) -> HistoryOut:
        """Finished runs and decisions in a room, newest first, optionally matching every word of q."""
        await member_room(session, room_id, principal)
        words = [w for w in q.split() if w][:8]

        def like(w: str) -> str:
            return "%" + w.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"

        run_stmt = select(models.Run).where(
            models.Run.room_id == room_id,
            models.Run.status.in_(("completed", "failed", "cancelled")),
            models.Run.kind.in_(("collab", "build", "review")),
        )
        if archived == "only":
            run_stmt = run_stmt.where(models.Run.archived_at.is_not(None))
        elif archived == "exclude":
            run_stmt = run_stmt.where(models.Run.archived_at.is_(None))
        for w in words:
            pat = like(w)
            run_stmt = run_stmt.where(
                models.Run.goal.ilike(pat, escape="\\")
                | func.coalesce(models.Run.brief, "").ilike(pat, escape="\\")
            )
        runs = list(
            (await session.scalars(run_stmt.order_by(models.Run.created_at.desc()).limit(limit))).all()
        )

        dec_stmt = (
            select(models.Decision, models.Run.goal)
            .join(models.Run, models.Run.id == models.Decision.run_id)
            .where(models.Decision.room_id == room_id)
        )
        for w in words:
            pat = like(w)
            dec_stmt = dec_stmt.where(
                models.Decision.question.ilike(pat, escape="\\")
                | func.coalesce(models.Decision.owner_note, "").ilike(pat, escape="\\")
                | func.coalesce(models.Decision.why, "").ilike(pat, escape="\\")
            )
        decs = (
            await session.execute(dec_stmt.order_by(models.Decision.created_at.desc()).limit(limit))
        ).all()
        atts = await attachments_for(session, [r.id for r in runs])
        return HistoryOut(
            runs=[run_out(r, atts.get(r.id)) for r in runs],
            decisions=[decision_out(d, goal) for d, goal in decs],
        )

    # ------------------------------------------------------------ connections (external agents)

    async def connection_out(
        session: AsyncSession, p: models.Principal, token: str | None = None
    ) -> ConnectionOut:
        last_used = await session.scalar(
            select(func.max(models.AgentToken.last_used_at)).where(models.AgentToken.principal_id == p.id)
        )
        rooms = (
            await session.scalars(
                select(models.Room)
                .join(models.RoomMember, models.RoomMember.room_id == models.Room.id)
                .where(models.RoomMember.principal_id == p.id)
                .order_by(models.Room.name)
            )
        ).all()
        return ConnectionOut(
            id=p.id,
            display_name=p.display_name,
            status="active" if p.status == "active" else "disabled",
            created_at=p.created_at,
            last_used_at=last_used,
            rooms=[ConnectionRoom(id=r.id, name=r.name) for r in rooms],
            token=token,
            mcp_port=settings.mcp_port,
        )

    async def own_connection(session: AsyncSession, connection_id: str) -> models.Principal:
        p = await session.get(models.Principal, connection_id)
        if p is None or p.kind != "external":
            raise api_error(404, "connection_not_found", "Connection not found")
        return p

    @app.get("/api/connections", response_model=list[ConnectionOut])
    async def list_connections(principal: PrincipalDep, session: SessionDep) -> list[ConnectionOut]:
        require_owner(principal)
        rows = await session.scalars(
            select(models.Principal)
            .where(models.Principal.kind == "external")
            .order_by(models.Principal.created_at)
        )
        return [await connection_out(session, p) for p in rows.all()]

    @app.post("/api/connections", response_model=ConnectionOut, status_code=201)
    async def create_connection(
        body: ConnectionIn, request: Request, principal: PrincipalDep, session: SessionDep
    ) -> ConnectionOut:
        """Create an external agent and its MCP token. The token is returned once, here."""
        require_owner(principal)
        taken = await session.scalar(
            select(models.Principal.id).where(
                func.lower(models.Principal.display_name) == body.display_name.lower()
            )
        )
        if taken is not None:
            raise api_error(409, "connection_exists", "An agent or connection with that name already exists")
        room_ids = list(dict.fromkeys(body.room_ids))
        if not room_ids:
            # Everything in a connection's rooms is sent to that agent's provider, so it only
            # gets the rooms the owner picks (a dedicated project room), never General by default.
            raise api_error(422, "validation_error", "room_ids: pick at least one room for this connection")
        for rid in room_ids:
            await member_room(session, rid, principal)
        p = models.Principal(
            id=new_id("ext"), kind="external", display_name=body.display_name, status="active"
        )
        session.add(p)
        await session.flush()
        for rid in room_ids:
            session.add(models.RoomMember(room_id=rid, principal_id=p.id))
        token = await issue_token(session, p.id)
        await session.commit()
        await audit(session, "connection.create", principal.id, p.id, request, rooms=room_ids)
        return await connection_out(session, p, token)

    @app.post("/api/connections/{connection_id}/rotate", response_model=ConnectionOut)
    async def rotate_connection(
        connection_id: str, request: Request, principal: PrincipalDep, session: SessionDep
    ) -> ConnectionOut:
        """New token; the old one stops working immediately. Also re-enables a revoked one."""
        require_owner(principal)
        p = await own_connection(session, connection_id)
        token = await issue_token(session, p.id)
        p.status = "active"
        await session.commit()
        await audit(session, "connection.rotate", principal.id, p.id, request)
        return await connection_out(session, p, token)

    @app.post("/api/connections/{connection_id}/revoke", response_model=ConnectionOut)
    async def revoke_connection(
        connection_id: str, request: Request, principal: PrincipalDep, session: SessionDep
    ) -> ConnectionOut:
        """Disconnect: the token stops working at once, and runs waiting for it fail."""
        require_owner(principal)
        p = await own_connection(session, connection_id)
        await revoke_tokens(session, p.id)
        p.status = "disabled"
        await session.execute(
            update(models.Run)
            .where(models.Run.status == "waiting", models.Run.waiting_for == p.id)
            .values(
                status="failed",
                error=f"{p.display_name} was disconnected.",
                finished_at=func.now(),
                waiting_for=None,
                waiting_instruction=None,
            )
        )
        await session.commit()
        await audit(session, "connection.revoke", principal.id, p.id, request)
        return await connection_out(session, p)

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
        tree_budget_usd=REPLY_TREE_BUDGET,
        max_runs_per_tree=settings.max_runs_per_tree,
    )
    if runs and getattr(app.state, "worker", None) is not None:
        app.state.worker.wake()
