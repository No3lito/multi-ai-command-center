"""Runs in a project room: the agents pick what to read, and their results are saved back.

Before the first step of a run in a room linked to a workspace project, the lead agent sees
the project card and the list of readable files (including the owner's linked folders) and
picks up to MAX_PICKS to read. The project card, the family page and the owner's rules are
always attached. Picked files are snapshotted like owner attachments, so every step sees the
same version and the existing limits apply.

When a run writes its decision brief, the brief and the run's final work are saved as
markdown in the project's briefs/ and outputs/ folders; each owner answer to a decision is
saved in decisions/. Saving is best effort: a full disk or a missing folder never fails a run.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date

from command_center.files import Entry
from command_center.workspace import PROJECTS_DIR, Project, Workspace

MAX_PICKS = 8
SELECT_MAX_TOKENS = 3000
FIRST_STEP = {"build": "design", "review": "share"}
_PICKS = re.compile(r"```(?:files|json)?[ \t]*\n(\[[\s\S]*?\])\s*```", re.IGNORECASE)


def first_step(kind: str) -> str:
    return FIRST_STEP.get(kind, "plan")


def context_paths(ws: Workspace, project: Project) -> list[str]:
    """Always read: the project card, its family page and the owner's standing rules."""
    paths = [f"{project.path}/PROJECT.md"]
    family_page = f"{PROJECTS_DIR}/{project.family}/{project.family.upper()}.md"
    # A project card can name more files every run must read: "always_read: a.md, sources/x.md"
    # (paths relative to the project), for example a facts sheet about the project's code.
    extras = [f"{project.path}/{p.strip().strip('/')}" for p in project.always_read]
    for extra in (family_page, "02-REFERENCE/owner-rules.md", *extras):
        try:
            if ws.real_path(extra).is_file():
                paths.append(extra)
        except (OSError, ValueError):
            continue
    return paths


def select_instruction(project: Project, goal: str, tree: list[Entry], attached: list[str]) -> str:
    listing = "\n".join(f"{e.path} ({(e.size or 0) // 1024} KB)" for e in tree) or "(no readable files)"
    have = ", ".join(attached) or "none"
    return (
        f"Before the work starts, choose what to read from the project '{project.title}' for this goal: "
        f"{goal.strip()}\n\n"
        f"Already attached: {have}.\n"
        f"Readable files in the project (path, size):\n{listing}\n\n"
        f"Pick at most {MAX_PICKS} files that matter most for the goal. Prefer summaries, reviews, "
        "specs and READMEs over raw data and logs; skip anything already attached; keep the total "
        "small. Reply with one or two sentences saying what you will read and why, then a fenced "
        "code block that starts with ```files and contains a JSON array of the exact paths "
        "(an empty array if nothing else is needed). Do not start the work itself yet."
    )


def parse_picks(text: str, allowed: set[str]) -> list[str]:
    match = None
    for m in _PICKS.finditer(text):
        match = m
    if match is None:
        return []
    try:
        raw = json.loads(match.group(1))
    except json.JSONDecodeError:
        return []
    picks: list[str] = []
    for item in raw if isinstance(raw, list) else []:
        if isinstance(item, str):
            path = item.strip().replace("\\", "/").strip("/")
            if path in allowed and path not in picks:
                picks.append(path)
        if len(picks) >= MAX_PICKS:
            break
    return picks


def strip_picks(text: str) -> str:
    match = None
    for m in _PICKS.finditer(text):
        match = m
    if match is None:
        return text
    return (text[: match.start()] + text[match.end() :]).strip() or "Picked the files to read."


@dataclass(frozen=True)
class RunRecord:
    run_id: str
    kind: str
    goal: str
    spent_usd: float


def _front(kind: str, run: RunRecord, extra: str = "") -> str:
    return (
        f"---\ntype: {kind}\nstatus: final\ncreated: {date.today().isoformat()}\n"
        f"run: {run.run_id}\nworkflow: {run.kind}\ncost_usd: {run.spent_usd:.4f}\n{extra}"
        f"tags: [{kind}, command-center]\n---\n"
    )


def save_brief(ws: Workspace, project: str, run: RunRecord, brief: str, questions: list[str]) -> str:
    title = run.goal.strip().splitlines()[0] if run.goal.strip() else "run"
    waiting = "\n".join(f"• {q}" for q in questions) or "• Nothing"
    body = (
        _front("brief", run)
        + f"# Brief: {title[:120]}\n\n## Goal\n{run.goal.strip()}\n\n## Brief\n{brief.strip()}\n\n"
        f"## Decisions raised\n{waiting}\n"
    )
    return ws.write_note(project, "briefs", title, body)


def save_output(ws: Workspace, project: str, run: RunRecord, author: str, text: str) -> str:
    title = run.goal.strip().splitlines()[0] if run.goal.strip() else "run"
    body = (
        _front("output", run, f"author: {author}\n")
        + f"# {title[:120]}\n\n_Final work from the run, by {author}._\n\n{text.strip()}\n"
    )
    return ws.write_note(project, "outputs", title, body)


def save_decision(
    ws: Workspace,
    project: str,
    *,
    question: str,
    answer: str,
    note: str | None,
    recommendation: str | None,
    follow_up_run_id: str | None,
    run_id: str,
) -> str:
    body = (
        f"---\ntype: decision\nanswer: {answer}\ncreated: {date.today().isoformat()}\n"
        f"run: {run_id}\nfollow_up_run: {follow_up_run_id or 'none'}\ntags: [decision, command-center]\n---\n"
        f"# Decision: {question.strip()[:150]}\n\n"
        f"**Owner's answer:** {answer}\n\n"
        f"**Owner's note:** {note or 'none'}\n\n"
        f"**Agents' recommendation:** {recommendation or 'none'}\n"
    )
    return ws.write_note(project, "decisions", question, body)
