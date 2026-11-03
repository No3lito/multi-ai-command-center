"""Code jobs: Claude and GPT change code together through a pull request; the owner merges.

FAKE ADAPTER and FAKE GITHUB evidence only: proves the workflow, the GitHub calls, the rules
and the limits, not the quality of real model output or GitHub's real behavior.
"""

from __future__ import annotations

import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select

from command_center import code_jobs, decisions
from command_center.code_jobs import GitHub, apply_edits, parse_edits
from command_center.db import models
from command_center.ids import new_id
from command_center.orchestrator.code_steps import parse_files, parse_review
from command_center.orchestrator.engine import BuiltinEngine
from command_center.providers.base import ChatRequest, ChatResponse
from tests.conftest import BACKEND, _free_port, run_server
from tests.fake_github import REPO, SAMPLE_FILES, TOKEN, FakeRepo, make_app
from tests.test_coordinator import logged_in
from tests.test_review_fixes import add_run, cfg, port_for, world  # noqa: F401  (fixture)

# ---------------------------------------------------------------- edit format and rules


def test_edits_modify_create_and_delete() -> None:
    text = (
        "Fixed the sign.\n```\nFILE: app/calc.py\n<<<<<<< SEARCH\n    return a - b\n=======\n"
        "    return a + b\n>>>>>>> REPLACE\nFILE: app/new.py\n<<<<<<< SEARCH\n=======\nX = 1\n"
        ">>>>>>> REPLACE\nDELETE: README.md\n```"
    )
    edits = parse_edits(text)
    assert [(e.path, e.search is None) for e in edits] == [
        ("app/calc.py", False),
        ("app/new.py", False),
        ("README.md", True),
    ]
    out = apply_edits({"app/calc.py": SAMPLE_FILES["app/calc.py"]}, set(SAMPLE_FILES), edits)
    assert out.errors == []
    assert out.files == {
        "app/calc.py": "def add(a, b):\n    return a + b\n",
        "app/new.py": "X = 1\n",
        "README.md": None,
    }
    assert code_jobs.strip_edits(text) == "Fixed the sign."


def test_edits_that_cannot_apply_say_why() -> None:
    current = {"app/calc.py": "x = 1\nx = 1\n", ".env": "SECRET=1\n"}
    existing = set(SAMPLE_FILES) | {".github/workflows/ci.yml"}

    def errors(block: str) -> list[str]:
        return apply_edits(current, existing, parse_edits(block)).errors

    assert "not found" in errors("FILE: app/calc.py\n<<<<<<< SEARCH\ny = 2\n=======\nz\n>>>>>>> REPLACE")[0]
    assert "2 times" in errors("FILE: app/calc.py\n<<<<<<< SEARCH\nx = 1\n=======\nz\n>>>>>>> REPLACE")[0]
    assert "secrets" in errors("FILE: .env\n<<<<<<< SEARCH\nSECRET=1\n=======\nS=2\n>>>>>>> REPLACE")[0]
    assert (
        "owner only"
        in errors("FILE: .github/workflows/ci.yml\n<<<<<<< SEARCH\n=======\nx\n>>>>>>> REPLACE")[0]
    )
    assert (
        "not shown" in errors("FILE: README.md\n<<<<<<< SEARCH\n# Sample\n=======\n# B\n>>>>>>> REPLACE")[0]
    )
    assert "inside the repository" in errors("FILE: ../x.py\n<<<<<<< SEARCH\n=======\nx\n>>>>>>> REPLACE")[0]
    assert code_jobs.blocked_reason(".env.example") is None


def test_small_parsers() -> None:
    assert parse_files('- read it\n```files\n["app/calc.py", "./tests/test_calc.py"]\n```') == [
        "app/calc.py",
        "tests/test_calc.py",
    ]
    assert parse_files("no block") == []
    assert parse_review("1. Fix it.\nVERDICT: CHANGES") == "changes"
    assert parse_review("Looks right.\n**VERDICT: APPROVE**") == "approve"
    assert parse_review("no verdict") == "changes"
    assert (
        code_jobs.branch_name("Fix the add() sign!", "run_01ABCDEF")
        == "agent/command-center/fix-the-add-sign-abcdef"
    )


def test_the_coding_team_is_offered_only_when_code_jobs_are_on() -> None:
    agents = [("Claude", "anthropic", True), ("GPT", "openai", True)]
    off = decisions.describe_executors(agents, [])
    on = decisions.describe_executors(agents, [], code_repo="No3lito/multi-ai-command-center")
    assert not any("Coding team" in line for line in off)
    assert any("Coding team (Claude and GPT)" in line and 'workflow "code"' in line for line in on)
    assert "code" in decisions.instruction_suffix(on, [], final_round=True)


# ---------------------------------------------------------------- the whole job, in process


class Scripted:
    """FAKE ADAPTER: answers each step of a code job from a script, and records the prompts."""

    id = "anthropic"
    simulated = False

    def __init__(self, writes: list[str], reviews: list[str], scope: str | None = None) -> None:
        self.writes, self.reviews = list(writes), list(reviews)
        self.scope = scope or 'Approach: fix the sign.\n```files\n["app/calc.py", "tests/test_calc.py"]\n```'
        self.prompts: list[tuple[str, str]] = []

    def capabilities(self, model: str):  # type: ignore[no-untyped-def]
        return None

    async def generate(self, req: ChatRequest) -> ChatResponse:
        prompt = req.messages[-1].content
        if "Pick the files you need to read" in prompt:
            kind, text = "scope", self.scope
        elif "Review " in prompt and "VERDICT: APPROVE" in prompt:
            kind, text = "review", self.reviews.pop(0)
        else:
            kind, text = "write", self.writes.pop(0)
        self.prompts.append((kind, prompt))
        return ChatResponse(text=text, input_tokens=2000, output_tokens=800, model=req.model)


FIX_SIGN = (
    "Changed minus to plus.\nFILE: app/calc.py\n<<<<<<< SEARCH\n    return a - b\n=======\n"
    "    return a + b\n>>>>>>> REPLACE"
)
ADD_TEST = (
    "Added a test for negatives.\nFILE: tests/test_calc.py\n<<<<<<< SEARCH\n"
    "    assert add(1, 2) == 3\n=======\n"
    "    assert add(1, 2) == 3\n    assert add(-1, 1) == 0\n>>>>>>> REPLACE"
)


@contextmanager
def fake_github(repo: FakeRepo) -> Iterator[Any]:
    transport = httpx.ASGITransport(app=make_app(repo))
    yield lambda: GitHub(TOKEN, REPO, api_url="http://fake-github", transport=transport)


async def code_job(
    w: dict[str, Any], adapter: Scripted, repo: FakeRepo, **run: Any
) -> tuple[models.Run, Any]:
    port = await port_for(w["sm"], cfg(w["url"]), adapter)
    with fake_github(repo) as gh:
        engine = BuiltinEngine(
            w["sm"],
            port,
            w["coordinator"],
            Decimal("0.25"),
            simulated=False,
            github=gh,
            code_ci_wait_seconds=5,
            code_ci_poll_seconds=0.01,
        )
        job = await add_run(
            w,
            kind="code",
            step="scope",
            goal="Fix add() so it adds",
            planner_id=w["agents"]["Claude"].id,
            critic_id=w["agents"]["GPT"].id,
            agent_id=None,
            max_turns=8,
            budget_usd=Decimal("3.00"),
            write_brief=False,
            **run,
        )
        for _ in range(40):
            if not await engine.step(job.id):
                break
    async with w["sm"]() as s:
        done = await s.get(models.Run, job.id)
        msgs = (
            await s.scalars(
                select(models.Message)
                .where(models.Message.correlation_id == job.id)
                .order_by(models.Message.seq)
            )
        ).all()
    assert done is not None
    return done, msgs


async def test_write_test_review_fix_then_one_card_for_the_owner(world: dict[str, Any]) -> None:  # noqa: F811
    """CI fails on the first push and the reviewer asks for changes; the writer fixes both in one
    round; CI passes, the reviewer approves, and the owner gets one merge card."""
    repo = FakeRepo(SAMPLE_FILES, ci=["failure", "success"])
    adapter = Scripted(
        writes=[FIX_SIGN, ADD_TEST],
        reviews=["1. Add a test with a negative number.\nVERDICT: CHANGES", "All good.\nVERDICT: APPROVE"],
    )
    run, msgs = await code_job(world, adapter, repo)
    assert run.status == "completed", run.error
    assert [k for k, _ in adapter.prompts] == ["scope", "write", "review", "write", "review"]
    state = run.code_state or {}
    assert state["pr"]["number"] == 1 and state["review"] == "approve"
    assert state["ci"]["status"] == "success"
    branch = repo.branches[state["branch"]]
    files = repo.commits[branch]["files"]
    assert files["app/calc.py"] == "def add(a, b):\n    return a + b\n"
    assert "assert add(-1, 1) == 0" in files["tests/test_calc.py"]
    assert repo.branches["main"] != branch and repo.prs[1]["state"] == "open"  # nothing merged yet
    assert repo.prs[1]["title"].startswith("[Claude + GPT]")
    # The fixer saw the review and the failing test's log.
    fix_prompt = adapter.prompts[3][1]
    assert "Add a test with a negative number" in fix_prompt and "assert -1 == 3" in fix_prompt
    # The reviewer saw the diff and the test result.
    assert "+    return a + b" in adapter.prompts[2][1] and "Automatic tests failed" in adapter.prompts[2][1]
    # The chat shows explanations, not raw edit blocks.
    assert not any("<<<<<<< SEARCH" in m.body_text for m in msgs)
    assert any("pull request [#1]" in m.body_text for m in msgs)
    assert run.verdict == "needs_you" and run.spent_usd <= Decimal("3.00")
    async with world["sm"]() as s:
        card = await s.scalar(select(models.Decision).where(models.Decision.run_id == run.id))
    assert card is not None and card.recommended == "approve"
    assert card.follow_up["code_pr"]["number"] == 1 and card.follow_up["on_more_info"]["workflow"] == "code"


async def test_blocked_edits_are_not_committed_and_go_back_to_the_writer(world: dict[str, Any]) -> None:  # noqa: F811
    repo = FakeRepo(SAMPLE_FILES)
    touch_env = "FILE: .env\n<<<<<<< SEARCH\nSECRET=do-not-touch\n=======\nSECRET=x\n>>>>>>> REPLACE"
    adapter = Scripted(writes=[touch_env, FIX_SIGN], reviews=["Fine.\nVERDICT: APPROVE"])
    run, msgs = await code_job(world, adapter, repo)
    assert run.status == "completed", run.error
    assert any("could not be applied" in m.body_text and ".env" in m.body_text for m in msgs)
    files = repo.commits[repo.branches[run.code_state["branch"]]]["files"]  # type: ignore[index]
    assert files[".env"] == "SECRET=do-not-touch\n"
    assert "Your previous edits could not be applied" in adapter.prompts[2][1]


async def test_a_job_that_never_agrees_stops_after_two_fix_rounds(world: dict[str, Any]) -> None:  # noqa: F811
    repo = FakeRepo(SAMPLE_FILES)
    no = "Still wrong.\nVERDICT: CHANGES"
    adapter = Scripted(
        writes=[FIX_SIGN, ADD_TEST, ADD_TEST.replace("== 0", "== 0  # again")], reviews=[no, no, no]
    )
    run, _ = await code_job(world, adapter, repo)
    assert run.status == "completed"
    assert [k for k, _ in adapter.prompts].count("review") == 3  # first review plus two fix rounds
    async with world["sm"]() as s:
        card = await s.scalar(select(models.Decision).where(models.Decision.run_id == run.id))
    assert card is not None and card.recommended == "more_info"


async def test_without_a_token_nothing_happens_and_it_says_so(world: dict[str, Any]) -> None:  # noqa: F811
    port = await port_for(world["sm"], cfg(world["url"]), Scripted([], []))
    engine = BuiltinEngine(world["sm"], port, world["coordinator"], Decimal("0.25"), simulated=False)
    job = await add_run(world, kind="code", step="scope", planner_id=world["agents"]["Claude"].id,
                        critic_id=world["agents"]["GPT"].id, agent_id=None, max_turns=8)  # fmt: skip
    assert await engine.step(job.id) is False
    async with world["sm"]() as s:
        run = await s.get(models.Run, job.id)
    assert run is not None and run.status == "failed" and "GITHUB_TOKEN" in (run.error or "")


async def test_a_wrong_token_fails_with_a_plain_reason(world: dict[str, Any]) -> None:  # noqa: F811
    port = await port_for(world["sm"], cfg(world["url"]), Scripted([], []))
    transport = httpx.ASGITransport(app=make_app(FakeRepo(SAMPLE_FILES)))
    engine = BuiltinEngine(
        world["sm"], port, world["coordinator"], Decimal("0.25"), simulated=False,
        github=lambda: GitHub("wrong", REPO, api_url="http://fake-github", transport=transport),
    )  # fmt: skip
    job = await add_run(world, kind="code", step="scope", planner_id=world["agents"]["Claude"].id,
                        critic_id=world["agents"]["GPT"].id, agent_id=None, max_turns=8)  # fmt: skip
    await engine.step(job.id)
    async with world["sm"]() as s:
        run = await s.get(models.Run, job.id)
    assert run is not None and run.status == "failed" and "Bad credentials" in (run.error or "")
    assert "GITHUB_TOKEN" in (run.error or "")


async def test_writer_and_reviewer_take_turns(world: dict[str, Any]) -> None:  # noqa: F811
    claude, gpt = world["agents"]["Claude"], world["agents"]["GPT"]
    async with world["sm"]() as s:
        first = await code_jobs.writer_and_reviewer(s, gpt, claude)
    assert [p.display_name for p in first] == ["Claude", "GPT"]
    await add_run(world, kind="code", step="done", status="completed", planner_id=claude.id, critic_id=gpt.id)
    async with world["sm"]() as s:
        second = await code_jobs.writer_and_reviewer(s, claude, gpt)
    assert [p.display_name for p in second] == ["GPT", "Claude"]


# ---------------------------------------------------------------- the owner's click, through the server


@contextmanager
def run_fake_github() -> Iterator[str]:
    port = _free_port()
    proc = subprocess.Popen([sys.executable, "-m", "tests.fake_github", "--port", str(port)], cwd=BACKEND)
    base = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 15
        while True:
            try:
                if httpx.get(f"{base}/_state", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            if time.monotonic() > deadline or proc.poll() is not None:
                raise RuntimeError("fake GitHub did not start")
            time.sleep(0.1)
        yield base
    finally:
        proc.terminate()
        proc.wait(timeout=10)


async def open_fake_pr(base: str, n: int) -> None:
    gh = GitHub(TOKEN, REPO, api_url=base)
    try:
        main = await gh.branch_sha("main")
        assert main is not None
        branch = f"agent/command-center/change-{n}"
        await gh.commit(branch, main, {"app/calc.py": f"# change {n}\n"}, f"change {n}")
        await gh.open_pr(branch, "main", f"[Claude + GPT] change {n}", "test")
    finally:
        await gh.aclose()


async def card_for_pr(url: str, n: int, room_id: str, owner_id: str, writer: str, reviewer: str) -> str:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    eng = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://", 1))
    try:
        async with async_sessionmaker(eng)() as s:
            run_id, dec_id = new_id("run"), new_id("dec")
            s.add(
                models.Run(
                    id=run_id, root_run_id=run_id, room_id=room_id, kind="code", status="completed",
                    step="done", goal="g", planner_id=writer, critic_id=reviewer, budget_usd=Decimal(3),
                    spent_usd=Decimal(0),
                    created_by=owner_id, max_turns=8,
                )
            )  # fmt: skip
            await s.flush()
            s.add(
                models.Decision(
                    id=dec_id, room_id=room_id, run_id=run_id, question=f"Merge pull request #{n}?",
                    follow_up={"code_pr": {"number": n, "url": f"https://github.com/{REPO}/pull/{n}",
                                           "title": "t"},
                               "on_approve": {"workflow": "none"}, "on_more_info": {"workflow": "code"}},
                    status="pending",
                )
            )  # fmt: skip
            await s.commit()
        return dec_id
    finally:
        await eng.dispose()


async def test_owner_approves_to_merge_and_declines_to_close(fresh_database_url: str, tmp_path: Path) -> None:
    with run_fake_github() as gh_base:
        env = {
            "GITHUB_TOKEN": TOKEN,
            "GITHUB_API_URL": gh_base,
            "CODE_REPO": REPO,
            "ANTHROPIC_API_KEY": "sk-ant-fake",
            "OPENAI_API_KEY": "sk-openai-fake",
        }
        with run_server(fresh_database_url, tmp_path, **env) as srv:
            async with logged_in(srv) as c:
                status = (await c.get("/api/code-jobs")).json()
                assert status == {"enabled": True, "repo": REPO, "budget_usd": 3.0, "reason": None}
                rooms = (await c.get("/api/rooms")).json()
                room_id = next(r["id"] for r in rooms if r["name"] == "General")
                me = (await c.get("/api/auth/me")).json()
                agents = {a["display_name"]: a for a in (await c.get("/api/agents")).json()}
                await open_fake_pr(gh_base, 1)
                await open_fake_pr(gh_base, 2)
                ids = [
                    await card_for_pr(
                        fresh_database_url, n, room_id, me["id"], agents["Claude"]["id"], agents["GPT"]["id"]
                    )
                    for n in (1, 2)
                ]
                cards = (await c.get(f"/api/rooms/{room_id}/decisions")).json()
                assert {d["code_pr"]["number"] for d in cards if d["code_pr"]} == {1, 2}
                r = await c.post(f"/api/decisions/{ids[0]}/answer", json={"answer": "approve"})
                assert r.status_code == 200, r.text
                assert "Merged pull request #1" in r.json()["code_result"]
                r = await c.post(f"/api/decisions/{ids[1]}/answer", json={"answer": "decline"})
                assert "Closed pull request #2" in r.json()["code_result"]
                async with httpx.AsyncClient() as raw:
                    state = (await raw.get(f"{gh_base}/_state")).json()
                assert state["prs"]["1"]["merged"] is True and state["prs"]["2"]["state"] == "closed"
                assert state["main_files"]["app/calc.py"] == "# change 1\n"
                # A new code job from the dashboard gets the job budget and starts by picking files.
                run = await c.post(
                    f"/api/rooms/{room_id}/runs",
                    json={"goal": "Fix add()", "workflow": "code", "planner_id": agents["Claude"]["id"],
                          "critic_id": agents["GPT"]["id"]},
                )  # fmt: skip
                assert run.status_code == 201, run.text
                assert (run.json()["kind"], run.json()["step"], run.json()["budget_usd"]) == (
                    "code",
                    "scope",
                    3.0,
                )
                await c.post(f"/api/runs/{run.json()['id']}/cancel")


async def test_code_jobs_are_off_without_a_token(client: httpx.AsyncClient) -> None:
    status = (await client.get("/api/code-jobs")).json()
    assert status["enabled"] is False and "GITHUB_TOKEN" in status["reason"]
    rooms = (await client.get("/api/rooms")).json()
    room_id = next(r["id"] for r in rooms if r["name"] == "General")
    agents = {a["display_name"]: a for a in (await client.get("/api/agents")).json()}
    r = await client.post(
        f"/api/rooms/{room_id}/runs",
        json={
            "goal": "x",
            "workflow": "code",
            "planner_id": agents["Claude"]["id"],
            "critic_id": agents["GPT"]["id"],
        },
    )
    assert r.status_code == 409 and r.json()["error"]["code"] == "code_jobs_off"
