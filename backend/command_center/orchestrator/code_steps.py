"""The steps of a code job (run kind "code"). See command_center/code_jobs.py for the rules.

scope  -> the writer picks the files it needs
write  -> the writer edits them; the edits are committed to a new branch and a pull request opens
ci     -> wait for the repository's automatic tests on that commit
review -> the other agent reviews the diff and the test result: APPROVE or CHANGES
fix    -> the writer applies the review and test findings (at most twice), then ci and review again
final  -> one card for the owner: merge the pull request or not

The state (branch, pull request, commits, CI, verdicts) lives in runs.code_state, so a restart
resumes where the job was. Every model call goes through ModelPort, so the job's own budget
and the instance-wide cap are enforced before each paid request.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from command_center import code_jobs
from command_center.code_jobs import GitHub, GitHubError
from command_center.db import models
from command_center.ids import new_id

if TYPE_CHECKING:
    from command_center.orchestrator.engine import BuiltinEngine

log = logging.getLogger(__name__)

WRITE_MAX_TOKENS = 16_000
SCOPE_MAX_TOKENS = 4_000
REVIEW_MAX_TOKENS = 10_000
# Writing several files can take minutes; the defaults (90 to 120 seconds) are for chat answers.
SCOPE_TIMEOUT_SECONDS = 240.0
WRITE_TIMEOUT_SECONDS = 600.0
REVIEW_TIMEOUT_SECONDS = 360.0
CI_START_GRACE_SECONDS = 180  # no CI run after this long: the repository has none for this branch
STEP_POLL_SLICE_SECONDS = 60  # one CI wait slice; the worker is free between slices
_FILES_BLOCK = re.compile(r"```files\s*\n(\[[\s\S]*?\])\s*```", re.IGNORECASE)
_VERDICT = re.compile(r"VERDICT:\s*\**\s*(APPROVE|CHANGES)", re.IGNORECASE)
RULES = (
    "Rules for this repository: TypeScript strict and Python type annotations; every change comes "
    "with tests; no secrets, API keys, .env files or health data anywhere; keep the change to what "
    "the goal needs; reuse existing helpers and follow the code style around you."
)


def parse_files(text: str) -> list[str]:
    blocks = list(_FILES_BLOCK.finditer(text))
    if not blocks:
        return []
    m = blocks[-1]
    try:
        raw = json.loads(m.group(1))
    except json.JSONDecodeError:
        return []
    if not isinstance(raw, list):
        return []
    paths = [str(p).strip().removeprefix("./") for p in raw if isinstance(p, str) and p.strip()]
    return [p for p in paths if code_jobs.blocked_reason(p) is None]


def parse_review(text: str) -> str:
    """approve or changes (the last VERDICT line wins; none counts as changes)."""
    found = _VERDICT.findall(text or "")
    return "approve" if found and found[-1].upper() == "APPROVE" else "changes"


class CodeSteps:
    def __init__(
        self, engine: BuiltinEngine, github: GitHub, *, ci_wait_seconds: float, ci_poll_seconds: float
    ):
        self.e = engine
        self.gh = github
        self.ci_wait_seconds = ci_wait_seconds
        self.ci_poll_seconds = ci_poll_seconds

    # ------------------------------------------------------------ helpers

    async def _names(self, run: models.Run) -> tuple[str, str]:
        async with self.e.sessionmaker() as s:
            w = await s.get(models.Principal, run.planner_id)
            r = await s.get(models.Principal, run.critic_id)
        return (w.display_name if w else "the writer", r.display_name if r else "the reviewer")

    async def _save(self, run: models.Run, state: dict[str, Any], **values: object) -> None:
        await self.e._update(run.id, code_state=dict(state), **values)
        run.code_state = dict(state)

    async def _say(self, run: models.Run, text: str, key: str, *, kind: str = "task.assign") -> str:
        msg = await self.e._post(
            run,
            self.e.coordinator_id,
            kind=kind,
            text=text,
            key=key,
            reply_to=run.last_message_id,
            data={"run_id": run.id, "status": "running", "step": run.step},
        )
        await self.e._update(run.id, last_message_id=msg)
        run.last_message_id = msg
        return msg

    async def _message_text(self, run: models.Run, sender: str, key: str) -> str:
        async with self.e.sessionmaker() as s:
            rows = (
                await s.scalars(
                    select(models.Message.body_text)
                    .where(
                        models.Message.sender_id == sender,
                        models.Message.correlation_id == run.id,
                        models.Message.idempotency_key.like(f"{run.id}:{key}:reply%"),
                    )
                    .order_by(models.Message.seq)
                )
            ).all()
        return "\n".join(r or "" for r in rows)

    async def _gh_failed(self, run: models.Run, exc: GitHubError) -> bool:
        hint = (
            " Check that GITHUB_TOKEN can read and write code and pull requests on "
            f"{self.gh.repo} and has not expired."
            if exc.status in (401, 403, 404)
            else ""
        )
        await self.e._fail(run, "failed", f"GitHub refused a step of this code job: {exc.message}.{hint}")
        return False

    # ------------------------------------------------------------ dispatch

    async def step(self, run: models.Run) -> bool:
        state: dict[str, Any] = dict(run.code_state or {})
        if run.wrap_up and run.step in ("scope", "write", "fix", "ci", "review"):
            if state.get("pr"):
                await self._save(run, state, step="final")
                return True
            await self.e._fail(run, "cancelled", "Stopped by the owner before any code was pushed.")
            return False
        try:
            if run.step == "scope":
                return await self._scope(run, state)
            if run.step in ("write", "fix"):
                return await self._write(run, state)
            if run.step == "ci":
                return await self._ci(run, state)
            if run.step == "review":
                return await self._review(run, state)
            if run.step == "final":
                return await self._final(run, state)
        except GitHubError as exc:
            return await self._gh_failed(run, exc)
        await self.e._update(run.id, status="completed", step="done")
        return False

    # ------------------------------------------------------------ scope

    async def _scope(self, run: models.Run, state: dict[str, Any]) -> bool:
        assert run.planner_id is not None
        writer, reviewer = await self._names(run)
        if "base_sha" not in state:
            base = await self.gh.default_branch()
            sha = await self.gh.branch_sha(base)
            if sha is None:
                await self.e._fail(run, "failed", f"The repository {self.gh.repo} has no {base} branch.")
                return False
            state.update(base=base, base_sha=sha, round=0, files=[], touched=[])
            await self._save(run, state)
        tree = await self.gh.tree(state["base_sha"])
        paths = [p for p in sorted(tree) if code_jobs.listed(p)]
        listing = "\n".join(f"{p} ({tree[p]:,} bytes)" for p in paths[:2500])
        assign = await self._say(
            run,
            f"Code job: @{writer} writes and @{reviewer} reviews. Step 1: @{writer}, pick the files "
            f"to read in {self.gh.repo}.",
            "scope:assign",
        )
        msg = await self.e._agent_turn(
            run,
            run.planner_id,
            f"You are the writer of a code change to the Command Center's own repository "
            f"({self.gh.repo}); {reviewer} will review it and the owner decides whether it merges. "
            f"Goal: {run.goal}\n\n{RULES}\n\n{_context(state)}"
            f"These are the repository's files on {state['base']} "
            f"(path and size):\n{listing}\n\nPick the files you need to read: the ones you will edit, "
            f"their tests, and anything needed to understand them (at most {code_jobs.MAX_SCOPE_FILES}). "
            "Answer with your approach in three to six short bullets, then one fenced block that "
            'starts with ```files and holds a JSON array of paths, for example ```files\n["a.py"]\n```.',
            "scope",
            assign,
            SCOPE_MAX_TOKENS,
            timeout_seconds=SCOPE_TIMEOUT_SECONDS,
        )
        if msg is None or msg == "__waiting__":
            return False
        text = await self._message_text(run, run.planner_id, "scope")
        wanted = [p for p in parse_files(text) if p in tree][: code_jobs.MAX_SCOPE_FILES]
        if not wanted:
            await self.e._fail(run, "failed", f"{writer} did not name any existing files to work on.")
            return False
        state["files"] = wanted
        await self._save(run, state, step="write")
        return True

    # ------------------------------------------------------------ write and fix

    async def _read(self, state: dict[str, Any]) -> tuple[dict[str, str], list[str]]:
        ref = state.get("head_sha") or state["base_sha"]
        current: dict[str, str] = {}
        skipped: list[str] = []
        total = 0
        for path in list(dict.fromkeys(state.get("files", []) + state.get("touched", []))):
            text = await self.gh.read(path, ref)
            if text is None:
                continue  # deleted on the branch, or binary
            if len(text) > code_jobs.MAX_FILE_CHARS or total + len(text) > code_jobs.MAX_READ_CHARS:
                skipped.append(path)
                continue
            total += len(text)
            current[path] = text
        return current, skipped

    async def _write(self, run: models.Run, state: dict[str, Any]) -> bool:
        assert run.planner_id is not None
        writer, reviewer = await self._names(run)
        fixing = run.step == "fix"
        rnd = int(state.get("round", 0))
        current, skipped = await self._read(state)
        tree = await self.gh.tree(state.get("head_sha") or state["base_sha"])
        shown = "\n\n".join(f"=== {p} ===\n{c}" for p, c in current.items())
        notes: list[str] = []
        if fixing:
            if state.get("owner_note"):
                notes.append(
                    "The owner sent it back with this note. Every sentence is a requirement, and it "
                    "overrides the original goal and background where they differ: "
                    f"{state['owner_note']}"
                )
            if state.get("review_text"):
                notes.append(f"{reviewer}'s review:\n{state['review_text'][-8000:]}")
            ci = state.get("ci") or {}
            if ci.get("status") == "failure":
                notes.append(
                    f"The automatic tests failed. {ci.get('summary', '')} Fix the KEY ERRORS below first; "
                    f"other log lines are usually noise.\n{ci.get('details', '')}"
                )
            if state.get("apply_errors"):
                notes.append(
                    "Your previous edits could not be applied:\n- " + "\n- ".join(state["apply_errors"])
                )
        if skipped:
            notes.append("Too large to show (do not edit them): " + ", ".join(skipped))
        label = f"Fix round {rnd} of {code_jobs.MAX_FIX_ROUNDS}" if fixing else "Step 2"
        assign = await self._say(
            run,
            f"{label}: @{writer}, " + ("apply the findings." if fixing else "write the change."),
            f"{run.step}{rnd}:assign",
        )
        task = (
            "Apply every required change from the notes below, and fix the failing tests if any. If a "
            "review point is wrong, say why in one sentence instead of changing the code."
            if fixing
            else "Write the change now."
        )
        self.e.raw_answers.pop(run.id, None)
        msg = await self.e._agent_turn(
            run,
            run.planner_id,
            f"Goal: {run.goal}\n\n{RULES}\n\n{_context(state)}"
            f"{task}\n\n{code_jobs.EDIT_FORMAT}\n\nStart with two to "
            "four sentences on what you changed and why, then the edit blocks."
            + ("\n\n" + "\n\n".join(notes) if notes else "")
            + f"\n\nCurrent files:\n\n{shown}",
            f"{run.step}{rnd}",
            assign,
            WRITE_MAX_TOKENS,
            postprocess=lambda t: _summary(t),
            timeout_seconds=WRITE_TIMEOUT_SECONDS,
        )
        if msg is None or msg == "__waiting__":
            return False
        key = f"{run.step}{rnd}"
        raw = self.e.raw_answers.pop(run.id, None)
        if raw is not None:
            # Keep the answer durably, so a restart before the commit does not lose (or re-buy) it.
            state["last_answer"] = {"key": key, "text": raw}
            await self._save(run, state)
        elif (state.get("last_answer") or {}).get("key") == key:
            raw = str(state["last_answer"]["text"])
        else:
            return await self._stop(
                run, state, "This step was interrupted after the answer arrived. Start the code job again."
            )
        edits = code_jobs.parse_edits(raw)
        if not edits:
            if fixing and state.get("pr"):
                await self._say(run, f"{writer} made no further changes.", f"{run.step}{rnd}:none")
                await self._save(run, state, step="final")
                return True
            await self.e._fail(run, "failed", f"{writer} proposed no code changes in the required format.")
            return False
        applied = code_jobs.apply_edits(current, set(tree), edits)
        if applied.errors or not applied.files:
            errors = applied.errors or ["The edits changed nothing."]
            state["apply_errors"] = errors
            if rnd < code_jobs.MAX_FIX_ROUNDS:
                state["round"] = rnd + 1
                await self._say(
                    run,
                    "The edits could not be applied, so nothing was committed:\n- " + "\n- ".join(errors[:8]),
                    f"{run.step}{rnd}:errors",
                    kind="error",
                )
                await self._save(run, state, step="fix")
                return True
            return await self._stop(
                run,
                state,
                "The edits could not be applied after the last round:\n- " + "\n- ".join(errors[:8]),
            )
        state.pop("apply_errors", None)
        branch = state.get("branch") or code_jobs.branch_name(run.goal, run.id)
        parent = state.get("head_sha") or state["base_sha"]
        first_line = code_jobs.no_skip_ci(re.sub(r"\s+", " ", run.goal)).strip()[:60]
        title = f"{'Fix review findings' if fixing else first_line}"
        sha = await self.gh.commit(
            branch,
            parent,
            applied.files,
            code_jobs.no_skip_ci(
                f"{title}\n\nWritten by {writer} and reviewed by {reviewer} in the Multi-AI Command Center "
                f"(run {run.id})."
            ),
        )
        state.update(branch=branch, head_sha=sha, ci_since=datetime.now(UTC).isoformat())
        state["touched"] = sorted(set(state.get("touched", [])) | set(applied.files))
        state.pop("ci", None)
        if not state.get("pr"):
            number, url = await self.gh.open_pr(
                branch,
                state["base"],
                f"[{writer} + {reviewer}] {first_line}",
                f"**Goal:** {code_jobs.no_skip_ci(run.goal)}\n\nWritten by {writer}, reviewed by {reviewer}, "
                f"in the Multi-AI Command Center (run `{run.id}`). Only the owner merges this, from the "
                "dashboard or here.",
            )
            state["pr"] = {"number": number, "url": url, "title": f"[{writer} + {reviewer}] {first_line}"}
        state.pop("last_answer", None)
        step_key = run.step
        await self._save(run, state, step="ci")  # one write: commit, pull request and next step
        changed = ", ".join(f"`{p}`" for p in sorted(applied.files))
        pr = state["pr"]
        await self._say(
            run,
            f"Pushed {len(applied.files)} file(s) to pull request [#{pr['number']}]({pr['url']}): {changed}. "
            "Waiting for the automatic tests.",
            f"{step_key}{rnd}:pushed",
        )
        return True

    async def _stop(self, run: models.Run, state: dict[str, Any], reason: str) -> bool:
        """End the job. With a pull request open, the owner still gets the card (merge, send
        back or close it), so nothing is left open without a decision."""
        if state.get("pr"):
            await self._say(run, reason, f"stop{state.get('round', 0)}", kind="error")
            state["stopped"] = reason
            await self._save(run, state, step="final")
            return True
        await self.e._fail(run, "failed", reason)
        return False

    # ------------------------------------------------------------ CI

    async def _ci(self, run: models.Run, state: dict[str, Any]) -> bool:
        since = datetime.fromisoformat(state.get("ci_since") or datetime.now(UTC).isoformat())
        slice_end = time.monotonic() + STEP_POLL_SLICE_SECONDS
        poll = min(self.ci_poll_seconds, STEP_POLL_SLICE_SECONDS / 2)
        while True:
            result = await self.gh.ci(state["head_sha"])
            waited = (datetime.now(UTC) - since).total_seconds()
            if result.status == "none" and waited < CI_START_GRACE_SECONDS:
                result.status = "pending"
            if result.status != "pending":
                break
            if waited >= self.ci_wait_seconds:
                result = code_jobs.CiResult(
                    "timeout", f"The automatic tests did not finish within {waited / 60:.0f} minutes."
                )
                break
            if time.monotonic() + poll > slice_end:
                return True  # free the worker; the next slice continues waiting
            await asyncio.sleep(poll)
        if result.status == "none":
            result.summary = "No automatic tests ran for this commit, so the change is not verified."
        state["ci"] = {"status": result.status, "summary": result.summary, "details": result.details}
        await self._save(run, state)
        await self._say(run, result.summary, f"ci{state.get('round', 0)}:result", kind="task.result")
        await self._save(run, state, step="review")
        return True

    # ------------------------------------------------------------ review

    async def _review(self, run: models.Run, state: dict[str, Any]) -> bool:
        assert run.critic_id is not None
        writer, reviewer = await self._names(run)
        rnd = int(state.get("round", 0))
        before: dict[str, str] = {}
        after: dict[str, str | None] = {}
        for path in state.get("touched", []):
            before[path] = await self.gh.read(path, state["base_sha"]) or ""
            after[path] = await self.gh.read(path, state["head_sha"])
        diff = code_jobs.diff_text(before, after)
        if len(diff) > code_jobs.MAX_DIFF_CHARS:
            diff = diff[: code_jobs.MAX_DIFF_CHARS] + "\n[diff cut off here]"
        ci = state.get("ci") or {}
        pr = state["pr"]
        assign = await self._say(
            run,
            f"Review: @{reviewer}, review pull request [#{pr['number']}]({pr['url']}).",
            f"review{rnd}:assign",
        )
        msg = await self.e._agent_turn(
            run,
            run.critic_id,
            f"Review {writer}'s code change for this goal: {run.goal}\n\n{RULES}\n\n{_context(state)}"
            f"{_owner_note(state)}Automatic tests: "
            f"{ci.get('summary', 'unknown')}\n\nCheck that it meets the goal, is correct, is tested, is "
            "safe (no secrets, no health data, nothing outside the goal) and fits the code around it. "
            "Do not ask for changes that are only taste. If changes are needed, list each one as a "
            "numbered instruction the writer can apply. End with exactly one line: VERDICT: APPROVE "
            f"or VERDICT: CHANGES.\n\nThe diff:\n{diff}",
            f"review{rnd}",
            assign,
            REVIEW_MAX_TOKENS,
            timeout_seconds=REVIEW_TIMEOUT_SECONDS,
        )
        if msg is None or msg == "__waiting__":
            return False
        text = await self._message_text(run, run.critic_id, f"review{rnd}")
        verdict = parse_review(text)
        state.update(review=verdict, review_text=text[-12_000:])
        # No CI run, or a timeout, is not a failure the writer can fix: conclude, unverified.
        if verdict == "approve" and ci.get("status") in ("success", "none", "timeout"):
            await self._save(run, state, step="final")
        elif rnd < code_jobs.MAX_FIX_ROUNDS:
            state["round"] = rnd + 1
            await self._save(run, state, step="fix")
        else:
            await self._save(run, state, step="final")
        return True

    # ------------------------------------------------------------ final card

    async def _final(self, run: models.Run, state: dict[str, Any]) -> bool:
        writer, reviewer = await self._names(run)
        pr = state.get("pr") or {}
        ci = state.get("ci") or {}
        agreed = (
            state.get("review") == "approve" and ci.get("status") == "success" and not state.get("stopped")
        )
        tests = ci.get("summary") or "The automatic tests did not run."
        if agreed:
            verdict_line = f"**Verdict:** Needs you. {writer} and {reviewer} agree the change is ready."
            recommended, rec = "approve", "Approve: both agents agree and the automatic tests passed."
        else:
            verdict_line = (
                f"**Verdict:** Needs you. {writer} and {reviewer} did not fully agree, or the tests did not "
                "pass."
            )
            recommended, rec = (
                "more_info",
                "Send it back with a note saying what to fix, or decline to close the pull request.",
            )
        brief = (
            f"{verdict_line}\n\n**Bottom line:** Pull request [#{pr.get('number')}]({pr.get('url')}) is "
            f"ready for your decision. {tests}\n\n**Done:**\n- {writer} wrote the change "
            f"({len(state.get('touched', []))} file(s)); {reviewer} reviewed it"
            f" ({'approved' if state.get('review') == 'approve' else 'asked for changes'}).\n\n"
            f"**Waiting on you:**\n- Merge pull request #{pr.get('number')} into {state.get('base', 'main')}?"
        )
        async with self.e.sessionmaker() as s:
            already = await s.scalar(
                select(models.Decision.id).where(models.Decision.run_id == run.id).limit(1)
            )
            if already is None and pr:
                s.add(
                    models.Decision(
                        id=new_id("dec"),
                        room_id=run.room_id,
                        run_id=run.id,
                        position=0,
                        question=(
                            f"Merge pull request #{pr['number']} ({pr.get('title', '')}) "
                            f"into {state.get('base', 'main')}?"
                        ),
                        why=(
                            f"{writer} wrote this change to the Command Center's code and {reviewer} "
                            f"reviewed it. {tests} Approving merges it on GitHub, and the automatic "
                            "updater loads it on your computer within about 5 minutes. Declining closes "
                            "the pull request."
                        ),
                        recommended=recommended,
                        recommendation=rec,
                        suggested_note=None
                        if agreed
                        else "Fix the reviewer's remaining points and make the tests pass.",
                        cost="Merging is free. Sending it back starts another code job (up to its budget).",
                        follow_up={
                            "code_pr": {
                                **pr,
                                "branch": state.get("branch"),
                                "head_sha": state.get("head_sha"),
                                "base": state.get("base", "main"),
                            },
                            "on_approve": {"workflow": "none"},
                            "on_more_info": {"workflow": "code", "goal": run.goal},
                        },
                        options=_card_options(ci.get("status") == "success"),
                        status="pending",
                    )
                )
                await s.commit()
        question = f"Merge pull request #{pr.get('number')} into {state.get('base', 'main')}?"
        await self._say(
            run,
            f"Code job finished. Pull request [#{pr.get('number')}]({pr.get('url')}): {tests} "
            f"{reviewer}'s verdict: {'APPROVE' if state.get('review') == 'approve' else 'CHANGES'}. "
            "Your decision is on the Decide tab.",
            "final",
            kind="task.result",
        )
        await self.e._update(
            run.id,
            status="completed",
            step="done",
            brief=brief,
            verdict="needs_you",
            pending_decisions=[question] if pr else [],
        )
        return False


def _card_options(tests_passed: bool) -> list[dict[str, str]]:
    """Ready-made answers for a finished code job. Merging is offered only on green."""
    send_back = {
        "label": "Send it back to fix",
        "detail": "The same writer fixes the remaining points, then tests and review run again.",
        "answer": "more_info",
        "note": "Fix the reviewer's remaining points and make the automatic tests pass.",
    }
    close = {
        "label": "Close it",
        "detail": "Throw this change away. Nothing changes in your code.",
        "answer": "decline",
        "note": "",
    }
    merge = {
        "label": "Merge it",
        "detail": "Put the change into main. Your computer updates within about 5 minutes.",
        "answer": "approve",
        "note": "",
    }
    return [merge, send_back, close] if tests_passed else [send_back, close]


def _owner_note(state: dict[str, Any]) -> str:
    """When the owner sent the job back, his note sets the scope of this round for both agents."""
    note = state.get("owner_note")
    if not note:
        return ""
    return (
        "The owner sent this pull request back with this note. It sets the scope of this round and "
        f"overrides the original goal and background where they differ:\n{note}\nJudge the change "
        "against the note: do not ask for work the note leaves for later jobs.\n\n"
    )


def _context(state: dict[str, Any]) -> str:
    """The discussion that led to this job (the agreed spec or plan), when there was one."""
    ctx = state.get("context")
    return (
        f"Background: the discussion that proposed this job agreed on the following.\n{ctx}\n\n"
        if ctx
        else ""
    )


def _summary(text: str) -> str:
    edits = code_jobs.parse_edits(text)
    files = sorted({e.path for e in edits})
    head = code_jobs.strip_edits(text) or "(no explanation)"
    if files:
        head += "\n\nEdits to: " + ", ".join(f"`{f}`" for f in files) + " (full diff on the pull request)."
    return head
