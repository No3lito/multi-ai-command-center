"""Code jobs: Claude and GPT change the Command Center's own code together, through GitHub.

One agent writes and the other reviews; they swap roles from one job to the next. Everything
goes through GitHub's REST API (no git binary, no local clone): read files on the default
branch, commit to a new branch, open a pull request, wait for the repository's automatic tests
(CI), review the diff, fix at most twice, then ask the owner one question: merge or not.
Approving merges the pull request; declining closes it. Nothing reaches main without that click.

This module holds the parts that do not need the orchestration engine: the GitHub client, the
edit format the writer uses, and the path rules. The steps live in orchestrator/code_steps.py.
"""

from __future__ import annotations

import base64
import difflib
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from command_center.config import Settings
from command_center.db import models

MAX_SCOPE_FILES = 15
MAX_FILE_CHARS = 60_000  # larger files are not offered for editing
MAX_READ_CHARS = 220_000  # all files shown to the writer in one step
MAX_DIFF_CHARS = 80_000
MAX_FIX_ROUNDS = 2
BRANCH_PREFIX = "agent/command-center/"
# Never listed, read or changed: build output, dependencies, lock files and binary assets.
_SKIP_DIRS = ("node_modules/", ".next/", "out/", "dist/", "__pycache__/", ".venv/", "test-results/")
_SKIP_SUFFIXES = (
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".webp", ".pdf", ".zip", ".woff", ".woff2", ".lock",
    ".pyc",
)  # fmt: skip
_SKIP_NAMES = ("package-lock.json", "uv.lock")


class GitHubError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"GitHub {status}: {message}")
        self.status = status
        self.message = message


# ---------------------------------------------------------------- path rules


_ERROR_LINE = re.compile(
    r"(^|\s)(Error:|AssertionError|Expected:|Received:|FAILED |\u2718|\u00d7|error TS\d+|Traceback|E\s{2,}\S|"
    r"\d+ failed|SyntaxError|TypeError|ModuleNotFoundError)"
)
_NOISE = re.compile(r"(##\[|database \"\S+\" does not exist|^\s*at\s)", re.IGNORECASE)


def key_errors(log: str, limit: int = 40) -> str:
    """The lines of a CI log that say what failed (with a line of context each), so the writer
    fixes the real failure instead of chasing noise such as service-container warnings."""
    lines = log.splitlines()
    keep: list[int] = []
    for i, line in enumerate(lines):
        if _ERROR_LINE.search(line) and not _NOISE.search(line):
            keep.extend(j for j in (i - 1, i, i + 1) if 0 <= j < len(lines))
    out: list[str] = []
    for i in dict.fromkeys(keep):
        if not _NOISE.search(lines[i]):
            out.append(lines[i].rstrip())
    return "\n".join(out[:limit])


def blocked_reason(path: str) -> str | None:
    """Why agents may not change this path, or None. Secrets, CI settings and anything
    outside the repository are off limits."""
    if (
        not path
        or path.startswith(("/", "~"))
        or "\\" in path
        or not path.isascii()
        or any(ord(c) < 32 or ord(c) == 127 for c in path)
    ):
        return "not a plain path inside the repository"
    parts = path.split("/")
    if any(p in ("", ".", "..") for p in parts):
        return "not a plain path inside the repository"
    lower = [p.lower() for p in parts]
    name = lower[-1]
    if ".git" in lower:
        return "git internals are never changed"
    if lower[0] == ".github" or name == "codeowners":
        return "CI and repository settings are changed by the owner only"
    if name.startswith(".env") and name != ".env.example":
        return "environment files can hold secrets"
    if name.endswith((".pem", ".key", ".p12", ".pfx")) or name in ("id_rsa", "id_ed25519"):
        return "key files are never changed"
    if name.endswith("docker-compose.override.yml"):
        return "generated on the owner's computer"
    return None


def listed(path: str) -> bool:
    lower = path.lower()
    return (
        not any(f"/{d}" in f"/{path}" for d in _SKIP_DIRS)
        and not lower.endswith(_SKIP_SUFFIXES)
        and path.rsplit("/", 1)[-1] not in _SKIP_NAMES
    )


# ---------------------------------------------------------------- edit format

EDIT_FORMAT = (
    "Write every change as edit blocks, exactly in this format:\n"
    "FILE: path/from/repository/root\n"
    "<<<<<<< SEARCH\n"
    "lines copied exactly from the current file (enough to be unique)\n"
    "=======\n"
    "the replacement lines\n"
    ">>>>>>> REPLACE\n"
    "Several blocks may follow one FILE line. The SEARCH text must match the current file "
    "exactly, including indentation, and occur once. To create a file, use an empty SEARCH "
    "section. To delete a file, write a line `DELETE: path`. Change only files you were shown "
    "or new files. Keep changes small and focused on the goal, and add or update tests."
)
_FILE = re.compile(r"^FILE:\s*`?([^\s`]+)`?\s*$")
_DELETE = re.compile(r"^DELETE:\s*`?([^\s`]+)`?\s*$")


@dataclass
class Edit:
    path: str
    search: str | None  # None: delete the file
    replace: str = ""


def parse_edits(text: str) -> list[Edit]:
    """Edit blocks in an answer. Code fences around them are ignored."""
    edits: list[Edit] = []
    current: str | None = None
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if m := _FILE.match(stripped):
            current = m.group(1)
        elif m := _DELETE.match(stripped):
            edits.append(Edit(m.group(1), None))
        elif stripped.startswith("<<<<<<< SEARCH") and current is not None:
            search: list[str] = []
            replace: list[str] = []
            i += 1
            while i < len(lines) and lines[i].strip() != "=======":
                search.append(lines[i])
                i += 1
            i += 1
            while i < len(lines) and not lines[i].strip().startswith(">>>>>>> REPLACE"):
                replace.append(lines[i])
                i += 1
            edits.append(Edit(current, "\n".join(search), "\n".join(replace)))
        i += 1
    return edits


def strip_edits(text: str) -> str:
    """The answer without its edit blocks: the writer's explanation, for the chat."""
    out: list[str] = []
    skipping = False
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("<<<<<<< SEARCH"):
            skipping = True
            continue
        if skipping:
            if s.startswith(">>>>>>> REPLACE"):
                skipping = False
            continue
        if _FILE.match(s) or _DELETE.match(s):
            continue
        out.append(line)
    text = "\n".join(out)
    text = re.sub(r"```[a-zA-Z0-9_-]*\s*```", "", text)  # fences left empty by the removal
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _with_newline_rules(content: str, search: str, replace: str) -> tuple[str, str]:
    # A SEARCH that covers whole lines matches "line\n" text; keep the file's line endings.
    if search and search + "\n" in content and not search.endswith("\n"):
        return search + "\n", replace + "\n" if replace else ""
    return search, replace


@dataclass
class Applied:
    files: dict[str, str | None] = field(default_factory=dict)  # changed path -> new content (None = deleted)
    errors: list[str] = field(default_factory=list)


def apply_edits(current: dict[str, str], existing: set[str], edits: list[Edit]) -> Applied:
    """Apply edits to the files the writer was shown. All or nothing: with any error the caller
    commits nothing and sends the errors back to the writer.

    current: path -> content of files the writer read. existing: every path in the repository.
    """
    out = Applied()
    work: dict[str, str | None] = dict(current)
    for e in edits:
        why = blocked_reason(e.path)
        if why:
            out.errors.append(f"{e.path}: not allowed ({why}).")
            continue
        if e.search is None:
            if e.path not in existing:
                out.errors.append(f"{e.path}: cannot delete a file that does not exist.")
            elif e.path not in current:
                out.errors.append(f"{e.path}: you were not shown this file, so you cannot delete it.")
            else:
                work[e.path] = None
            continue
        content = work.get(e.path)
        if content is None:
            if e.path in existing and e.path not in current:
                out.errors.append(f"{e.path}: you were not shown this file; ask for it before editing.")
                continue
            if e.search.strip():
                out.errors.append(f"{e.path}: the file does not exist; use an empty SEARCH to create it.")
                continue
            work[e.path] = e.replace if e.replace.endswith("\n") or not e.replace else e.replace + "\n"
            continue
        if not e.search.strip():
            out.errors.append(f"{e.path}: an empty SEARCH only creates new files; this file exists.")
            continue
        search, replace = _with_newline_rules(content, e.search, e.replace)
        count = content.count(search)
        if count != 1:
            hint = "not found" if count == 0 else f"found {count} times; include more lines"
            first = e.search.strip().splitlines()[0][:80]
            out.errors.append(f"{e.path}: SEARCH text {hint} (starts with: {first!r}).")
            continue
        work[e.path] = content.replace(search, replace, 1)
    for path, content in work.items():
        if content != current.get(path) or (content is None and path in existing):
            out.files[path] = content
    return out


def diff_text(before: dict[str, str], after: dict[str, str | None]) -> str:
    """Unified diff of the changed files, for the reviewer."""
    parts: list[str] = []
    for path, new in sorted(after.items()):
        old = before.get(path, "")
        parts.extend(
            difflib.unified_diff(
                old.splitlines(keepends=True),
                (new or "").splitlines(keepends=True),
                fromfile=f"a/{path}",
                tofile="/dev/null" if new is None else f"b/{path}",
            )
        )
    return "".join(parts)


_SKIP_CI = re.compile(
    r"\[\s*(skip|no)[ _-]?(ci|actions)\s*\]|\[\s*(ci|actions)[ _-]?skip\s*\]|\*\*\*NO_CI\*\*\*", re.I
)


def no_skip_ci(text: str) -> str:
    """Commit messages and titles must never switch the automatic tests off."""
    return _SKIP_CI.sub("", text)


def check_pr_for_merge(pr: dict[str, Any], head_sha: str, base: str) -> str | None:
    """Why this pull request must not be merged by the card, or None."""
    if pr.get("merged"):
        return None
    if pr.get("state") != "open":
        return "it is no longer open"
    head = pr.get("head") or {}
    if not str(head.get("ref") or "").startswith(BRANCH_PREFIX):
        return "it is not a code job branch"
    if str((pr.get("base") or {}).get("ref") or "") != base:
        return f"it does not target {base}"
    if head_sha and str(head.get("sha") or "") != head_sha:
        return "its branch changed after the review; send it back to review the new commits"
    return None


def branch_name(goal: str, run_id: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", goal.lower()).strip("-")[:40].strip("-") or "change"
    return f"{BRANCH_PREFIX}{slug}-{run_id[-6:].lower()}"


# ---------------------------------------------------------------- GitHub


@dataclass
class CiResult:
    status: str  # success | failure | pending | none
    summary: str = ""
    details: str = ""  # failed jobs and steps, and the end of their logs (for the fixer)


class GitHub:
    """The few GitHub REST calls a code job needs. The token never leaves this object."""

    def __init__(
        self,
        token: str,
        repo: str,
        *,
        api_url: str = "https://api.github.com",
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.repo = repo
        self._client = httpx.AsyncClient(
            base_url=api_url.rstrip("/"),
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "multi-ai-command-center",
            },
            transport=transport,
            timeout=timeout,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _req(self, method: str, path: str, **kw: Any) -> Any:
        try:
            resp = await self._client.request(method, path, **kw)
        except httpx.HTTPError as exc:
            raise GitHubError(0, f"could not reach GitHub ({type(exc).__name__})") from exc
        if resp.status_code >= 400:
            try:
                body = resp.json()
                message = str(body.get("message") or resp.text)[:300]
                errors = body.get("errors")
                if errors:
                    message += f" {str(errors)[:300]}"
            except ValueError:
                message = resp.text[:300]
            raise GitHubError(resp.status_code, message)
        return resp.json() if resp.content else None

    def _r(self, path: str) -> str:
        return f"/repos/{self.repo}{path}"

    async def default_branch(self) -> str:
        return str((await self._req("GET", self._r(""))).get("default_branch") or "main")

    async def branch_sha(self, branch: str) -> str | None:
        try:
            ref = await self._req("GET", self._r(f"/git/ref/heads/{quote(branch)}"))
        except GitHubError as exc:
            if exc.status == 404:
                return None
            raise
        return str(ref["object"]["sha"])

    async def tree(self, sha: str) -> dict[str, int]:
        """Every file path at this commit, with its size in bytes."""
        data = await self._req("GET", self._r(f"/git/trees/{sha}"), params={"recursive": "1"})
        return {
            item["path"]: int(item.get("size") or 0)
            for item in data.get("tree", [])
            if item["type"] == "blob"
        }

    async def read(self, path: str, ref: str) -> str | None:
        try:
            data = await self._req("GET", self._r(f"/contents/{quote(path)}"), params={"ref": ref})
        except GitHubError as exc:
            if exc.status == 404:
                return None
            raise
        if not isinstance(data, dict) or data.get("encoding") != "base64":
            return None
        try:
            return base64.b64decode(data.get("content") or "").decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return None  # binary

    async def commit(self, branch: str, parent: str, files: dict[str, str | None], message: str) -> str:
        """One commit on top of parent with these files changed (None deletes); moves or creates
        the branch to it. Returns the new commit's sha."""
        parent_commit = await self._req("GET", self._r(f"/git/commits/{parent}"))
        entries: list[dict[str, Any]] = [
            {"path": p, "mode": "100644", "type": "blob", "sha": None}
            if c is None
            else {"path": p, "mode": "100644", "type": "blob", "content": c}
            for p, c in sorted(files.items())
        ]
        tree = await self._req(
            "POST", self._r("/git/trees"), json={"base_tree": parent_commit["tree"]["sha"], "tree": entries}
        )
        new = await self._req(
            "POST",
            self._r("/git/commits"),
            json={"message": message, "tree": tree["sha"], "parents": [parent]},
        )
        sha = str(new["sha"])
        if await self.branch_sha(branch) is None:
            await self._req("POST", self._r("/git/refs"), json={"ref": f"refs/heads/{branch}", "sha": sha})
        else:
            await self._req(
                "PATCH", self._r(f"/git/refs/heads/{quote(branch)}"), json={"sha": sha, "force": False}
            )
        return sha

    async def open_pr(self, branch: str, base: str, title: str, body: str) -> tuple[int, str]:
        try:
            pr = await self._req(
                "POST", self._r("/pulls"), json={"title": title, "head": branch, "base": base, "body": body}
            )
        except GitHubError as exc:
            if exc.status != 422 or "already exists" not in exc.message:
                raise
            owner = self.repo.split("/", 1)[0]
            found = await self._req(
                "GET", self._r("/pulls"), params={"head": f"{owner}:{branch}", "state": "open"}
            )
            if not found:
                raise
            pr = found[0]
        return int(pr["number"]), str(pr["html_url"])

    async def pr_state(self, number: int) -> dict[str, Any]:
        data: dict[str, Any] = await self._req("GET", self._r(f"/pulls/{number}"))
        return data

    async def ci(self, sha: str) -> CiResult:
        """The combined result of every workflow run for this commit."""
        data = await self._req("GET", self._r("/actions/runs"), params={"head_sha": sha, "per_page": 50})
        runs = data.get("workflow_runs") or []
        if not runs:
            return CiResult("none", "No automatic tests have started yet.")
        if any(r.get("status") != "completed" for r in runs):
            return CiResult("pending", "Automatic tests are still running.")
        failed = [r for r in runs if r.get("conclusion") not in ("success", "skipped", "neutral")]
        if not failed:
            return CiResult("success", "Automatic tests passed.")
        names: list[str] = []
        errors: list[str] = []
        tails: list[str] = []
        for r in failed[:3]:
            jobs = await self._req("GET", self._r(f"/actions/runs/{r['id']}/jobs"), params={"per_page": 50})
            for job in jobs.get("jobs") or []:
                if job.get("conclusion") in ("success", "skipped", "neutral"):
                    continue
                steps = [s["name"] for s in job.get("steps") or [] if s.get("conclusion") == "failure"]
                label = job["name"] + (f" ({', '.join(steps)})" if steps else "")
                if label in names:
                    continue  # the same job ran for the push and for the pull request
                names.append(label)
                log = await self._log(int(job["id"]))
                found = key_errors(log)
                if found:
                    errors.append(f"Job {job['name']}:\n{found}")
                tails.append(f"End of the {job['name']} log:\n{log[-3000:]}")
        summary = "Automatic tests failed: " + ("; ".join(names) or "see GitHub") + "."
        if errors:
            first = next((ln for ln in errors[0].splitlines()[1:] if ln.strip()), "")
            summary += f" First error: {first.strip()[:200]}"
        details = (
            "KEY ERRORS (fix these):\n" + "\n\n".join(errors) + "\n\n" if errors else ""
        ) + "\n\n".join(tails)
        return CiResult("failure", summary, details[:14_000])

    async def _log(self, job_id: int) -> str:
        """A failed job's log without timestamps (best effort; the log host is a redirect)."""
        try:
            resp = await self._client.get(self._r(f"/actions/jobs/{job_id}/logs"), follow_redirects=True)
        except httpx.HTTPError:
            return ""
        if resp.status_code != 200:
            return ""
        lines = [re.sub(r"^\S+Z ", "", ln) for ln in resp.text.splitlines()]
        return "\n".join(lines)[-200_000:]

    async def merge(self, number: int, title: str, head_sha: str) -> str:
        """Squash-merge, only if the pull request still points at the commit that was reviewed."""
        data = await self._req(
            "PUT",
            self._r(f"/pulls/{number}/merge"),
            json={"merge_method": "squash", "commit_title": title, "sha": head_sha},
        )
        return str(data.get("sha") or "")

    async def close(self, number: int) -> None:
        await self._req("PATCH", self._r(f"/pulls/{number}"), json={"state": "closed"})

    async def comment(self, number: int, body: str) -> None:
        await self._req("POST", self._r(f"/issues/{number}/comments"), json={"body": body})


def github_from(settings: Settings, transport: httpx.AsyncBaseTransport | None = None) -> GitHub | None:
    if not settings.code_jobs_enabled or settings.github_token is None:
        return None
    return GitHub(
        settings.github_token.get_secret_value().strip(),
        settings.code_repo,
        api_url=settings.github_api_url,
        transport=transport,
    )


# ---------------------------------------------------------------- who writes


async def writer_and_reviewer(
    session: AsyncSession, a: models.Principal, b: models.Principal
) -> tuple[models.Principal, models.Principal]:
    """They take turns: on even-numbered jobs the Claude agent writes, on odd ones GPT does."""
    count = await session.scalar(
        select(func.count()).select_from(models.Run).where(models.Run.kind == "code")
    )
    pa = await session.get(models.AgentProfile, a.id)
    first, second = (a, b) if pa is not None and pa.provider == "anthropic" else (b, a)
    return (first, second) if (count or 0) % 2 == 0 else (second, first)


EXECUTOR_LINE = (
    "Coding team ({names}): can change the Command Center's own code in {repo}. One writes, the "
    "other reviews, the automatic tests run, and the owner merges with one click. To use it, set "
    'workflow "code" with the full change as the goal (what to change, why, and how to test it).'
)
