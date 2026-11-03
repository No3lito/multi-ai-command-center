"""The owner's project workspace: layout, linked read-only sources, project rooms, auto-saving.

FAKE PROVIDER evidence for the run parts: proves which files are read, attached and saved,
not model quality. The linked-source mounts are simulated with a plain folder (as Docker
mounts them under SOURCES_ROOT).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from command_center.files import FileAccessError
from command_center.workspace import INDEX_END, INDEX_START, Workspace, mount_key
from tests.conftest import run_fake_providers, run_server
from tests.test_bridge import call, connect, mcp
from tests.test_coordinator import general_and_agents, logged_in, wait_run

MEME = "01-PROJECTS/trading/meme-coin-strategy"


@pytest.fixture
def layout(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "Workspace"
    sources = tmp_path / "sources"
    proj = root / MEME
    for sub in ("sources", "briefs", "decisions", "outputs"):
        (proj / sub).mkdir(parents=True)
    (proj / "PROJECT.md").write_text(
        "---\ntype: project\nfamily: trading\nstatus: active\n---\n# Meme coin strategy\n\n"
        "## Goal\nFind an edge or stop.\n\n## Status\n• Paper only.\n"
    )
    (root / "01-PROJECTS/trading/TRADING.md").write_text("# Trading family\nShared rules.\n")
    (root / "02-REFERENCE").mkdir(parents=True)
    (root / "02-REFERENCE/owner-rules.md").write_text("# Rules\nNo real trades.\n")
    (root / "00-INBOX").mkdir()
    (root / "00-INBOX/README.md").write_text("# Inbox\n")
    (root / "00-INBOX/meme-coin-ideas.md").write_text("try volume filter\n")
    (root / "10-SYSTEM").mkdir()
    (root / "10-SYSTEM/INDEX.md").write_text("# Map of every project\n\nMy own notes stay.\n")
    links = {
        "links": [
            {"project": MEME, "name": "trading-review", "target": "C:\\Users\\x\\Trading-Review"},
            {"project": "../outside", "name": "evil", "target": "C:\\"},
            {"project": MEME, "name": "bad/name", "target": "C:\\"},
        ]
    }
    (root / "10-SYSTEM/links.json").write_text(json.dumps(links))
    # The junction as Docker sees it: a link that cannot be followed.
    os.symlink("/nonexistent/C/Users/x/Trading-Review", proj / "sources/trading-review")
    mounted = sources / mount_key(MEME, "trading-review")
    (mounted / "logs").mkdir(parents=True)
    (mounted / "node_modules").mkdir()
    (mounted / "README.md").write_text("# Review packet\nNo edge at 5 s.\n")
    (mounted / "HYPOTHESIS-REVIEW.md").write_text("H123 weak\n")
    (mounted / "logs/run.log").write_text("noise\n")
    (mounted / "node_modules/pkg.md").write_text("vendor\n")
    (tmp_path / "secret.md").write_text("outside the workspace\n")
    os.symlink(tmp_path / "secret.md", root / "00-INBOX/sneaky.md")
    return root, sources


# ---------------------------------------------------------------- the workspace module


def test_linked_sources_are_listed_and_read_through_the_mount(layout: tuple[Path, Path]) -> None:
    root, sources = layout
    ws = Workspace(root, sources)
    assert [link.prefix for link in ws.links()] == [f"{MEME}/sources/trading-review"], "bad links are ignored"
    listed = ws.list_dir(f"{MEME}/sources")
    assert [(e.name, e.path, e.type) for e in listed] == [
        ("trading-review", f"{MEME}/sources/trading-review", "dir")
    ]
    inside = {e.name for e in ws.list_dir(f"{MEME}/sources/trading-review")}
    assert {"README.md", "HYPOTHESIS-REVIEW.md", "logs", "node_modules"} <= inside
    snap = ws.read_snapshot(f"{MEME}/sources/trading-review/README.md")
    assert snap.path == f"{MEME}/sources/trading-review/README.md" and "No edge" in snap.content


@pytest.mark.parametrize(
    "bad",
    [
        f"{MEME}/sources/trading-review/../../../../secret.md",
        "/etc/passwd",
        "C:/Windows/win.ini",
        "../secret.md",
        "00-INBOX/sneaky.md",
    ],
)
def test_paths_cannot_leave_the_workspace_or_a_linked_folder(layout: tuple[Path, Path], bad: str) -> None:
    root, sources = layout
    with pytest.raises(FileAccessError):
        Workspace(root, sources).read_snapshot(bad)


def test_unconnected_link_says_how_to_fix_it(layout: tuple[Path, Path]) -> None:
    root, _ = layout
    with pytest.raises(FileAccessError, match=r"workspace-mounts\.ps1"):
        Workspace(root, None).read_snapshot(f"{MEME}/sources/trading-review/README.md")


def test_tree_for_agents_skips_logs_and_vendor_folders(layout: tuple[Path, Path]) -> None:
    root, sources = layout
    paths = [e.path for e in Workspace(root, sources).tree(MEME)]
    assert f"{MEME}/PROJECT.md" in paths and f"{MEME}/sources/trading-review/README.md" in paths
    assert not any("/logs/" in p or "node_modules" in p for p in paths)


def test_suggestions_match_goal_words_against_names_and_contents(layout: tuple[Path, Path]) -> None:
    root, sources = layout
    ws = Workspace(root, sources)
    hits = ws.suggest(MEME, "Check the hypothesis notes for H123")
    assert hits[0][0].path == f"{MEME}/sources/trading-review/HYPOTHESIS-REVIEW.md"
    assert set(hits[0][2]) == {"hypothesis", "h123"}
    assert all("logs" not in e.path and e.path != f"{MEME}/PROJECT.md" for e, _, _ in hits)
    assert ws.suggest(MEME, "please review the project") == [], "stop words alone match nothing"


def test_project_cards_can_name_files_every_run_reads(layout: tuple[Path, Path]) -> None:
    from command_center import project_files

    root, sources = layout
    card = root / MEME / "PROJECT.md"
    card.write_text(
        card.read_text().replace(
            "status: active", "status: active\nalways_read: sources/trading-review/README.md"
        )
    )
    ws = Workspace(root, sources)
    project = ws.project(MEME)
    assert project is not None and project.always_read == ("sources/trading-review/README.md",)
    assert f"{MEME}/sources/trading-review/README.md" in project_files.context_paths(ws, project)


def test_projects_create_and_index(layout: tuple[Path, Path]) -> None:
    root, sources = layout
    ws = Workspace(root, sources)
    [meme] = ws.projects()
    assert (meme.path, meme.family, meme.title, meme.status) == (
        MEME,
        "trading",
        "Meme coin strategy",
        "active",
    )
    assert meme.goal == "Find an edge or stop."
    new = ws.create_project("Fantasy Sports", "Draft Helper", "Win the league.")
    assert new.path == "01-PROJECTS/fantasy-sports/draft-helper"
    for sub in ("sources", "briefs", "decisions", "outputs", "notes"):
        assert (root / new.path / sub).is_dir()
    assert (root / "01-PROJECTS/fantasy-sports/FANTASY-SPORTS.md").exists()
    assert "Win the league." in (root / new.path / "PROJECT.md").read_text()
    assert ws.create_project("Fantasy Sports", "Draft Helper") == new, (
        "creating twice returns the same project"
    )
    index = (root / "10-SYSTEM/INDEX.md").read_text()
    assert "My own notes stay." in index and INDEX_START in index and INDEX_END in index
    assert "Draft Helper" in index and "Meme coin strategy" in index and "trading-review" in index
    ws.refresh_index()
    assert (root / "10-SYSTEM/INDEX.md").read_text().count(INDEX_START) == 1, "regenerated in place"


def test_writes_go_only_to_project_folders_and_never_overwrite(layout: tuple[Path, Path]) -> None:
    root, sources = layout
    ws = Workspace(root, sources)
    first = ws.write_note(MEME, "briefs", "No edge", "one")
    second = ws.write_note(MEME, "briefs", "No edge", "two")
    assert first != second and first.startswith(f"{MEME}/briefs/") and first.endswith("-brief-no-edge.md")
    assert (root / first).read_text() == "one\n"
    with pytest.raises(FileAccessError):
        ws.write_note(MEME, "sources", "x", "y")  # type: ignore[arg-type]
    with pytest.raises(FileAccessError):
        ws.write_note("01-PROJECTS/trading/nope", "outputs", "x", "y")


def test_inbox_filing(layout: tuple[Path, Path]) -> None:
    root, sources = layout
    ws = Workspace(root, sources)
    assert [e.name for e in ws.inbox()] == ["meme-coin-ideas.md"], (
        "README and links pointing outside are hidden"
    )
    moved = ws.file_from_inbox("meme-coin-ideas.md", MEME)
    assert moved == f"{MEME}/notes/meme-coin-ideas.md" and not (root / "00-INBOX/meme-coin-ideas.md").exists()
    for bad in ("../x.md", "README.md", "sneaky.md"):
        with pytest.raises(FileAccessError):
            ws.file_from_inbox(bad, MEME)


# ---------------------------------------------------------------- end to end

PICKED = [f"{MEME}/sources/trading-review/README.md", "../../etc/passwd"]
PICK = "\nI will read the review.\n```files\n" + json.dumps(PICKED) + "\n```"
BRIEF = (
    "\n**Bottom line:** Retest H123 only.\n```decisions\n"
    + json.dumps(
        [{"question": "Approve the audit?", "recommended": "approve", "recommendation": "Approve: cheap."}]
    )
    + "\n```"
)


async def test_project_rooms_read_pick_and_save(
    tmp_path: Path, fresh_database_url: str, layout: tuple[Path, Path]
) -> None:
    root, sources = layout
    with run_fake_providers(reply_suffix=PICK + BRIEF) as fake:
        env = {
            "ANTHROPIC_API_KEY": "sk-ant-fake",
            "OPENAI_API_KEY": "sk-openai-fake",
            "ANTHROPIC_BASE_URL": fake,
            "OPENAI_BASE_URL": f"{fake}/v1",
            "LIVE_BUDGET_USD": "2.00",
            "FILES_ROOT": str(root),
            "SOURCES_ROOT": str(sources),
        }
        with run_server(fresh_database_url, tmp_path, **env) as srv:
            async with logged_in(srv) as c:
                ws = (await c.get("/api/workspace")).json()
                assert ws["structured"] and [p["path"] for p in ws["projects"]] == [MEME]
                assert ws["inbox"] == [{"name": "meme-coin-ideas.md", "size": 18, "suggested_project": MEME}]

                # Rooms: link an existing project, or create a new one with the room.
                bad = await c.post("/api/rooms", json={"name": "X", "project_path": "01-PROJECTS/nope/nope"})
                assert bad.status_code == 422
                room = (await c.post("/api/rooms", json={"name": "Meme", "project_path": MEME})).json()
                assert room["project_path"] == MEME
                fresh = await c.post(
                    "/api/rooms",
                    json={"name": "Fantasy", "new_project": {"family": "Fun", "name": "Draft Helper"}},
                )
                assert fresh.json()["project_path"] == "01-PROJECTS/fun/draft-helper"
                assert (root / "01-PROJECTS/fun/draft-helper/PROJECT.md").exists()
                general, agents = await general_and_agents(c)
                linked = await c.put(f"/api/rooms/{general}/project", json={"project_path": MEME})
                assert linked.json()["project_path"] == MEME
                assert (await c.put(f"/api/rooms/{general}/project", json={})).json()["project_path"] is None

                sugg = (
                    await c.get(f"/api/rooms/{room['id']}/suggest-files", params={"goal": "hypothesis H123"})
                ).json()
                assert sugg["suggested"][0]["path"] == f"{MEME}/sources/trading-review/HYPOTHESIS-REVIEW.md"
                assert (
                    f"{MEME}/PROJECT.md" in sugg["always"] and "02-REFERENCE/owner-rules.md" in sugg["always"]
                )

                # The owner browses linked sources like any folder.
                listing = (
                    await c.get("/api/files", params={"path": f"{MEME}/sources/trading-review"})
                ).json()
                assert "README.md" in {e["name"] for e in listing["entries"]}

                # A run in the project room: rules and card attached, the lead picks a file.
                for a in ("Claude", "GPT"):
                    await c.post(f"/api/rooms/{room['id']}/members", json={"principal_id": agents[a]["id"]})
                r = await c.post(
                    f"/api/rooms/{room['id']}/runs",
                    json={
                        "goal": "Review the packet",
                        "planner_id": agents["Claude"]["id"],
                        "critic_id": agents["GPT"]["id"],
                    },
                )
                assert r.status_code == 201, r.text
                assert r.json()["step"] == "select"
                done = await wait_run(c, r.json()["id"], within=30)
                assert done["status"] == "completed", done
                assert {a["path"] for a in done["attachments"]} == {
                    f"{MEME}/PROJECT.md",
                    "01-PROJECTS/trading/TRADING.md",
                    "02-REFERENCE/owner-rules.md",
                    f"{MEME}/sources/trading-review/README.md",
                }, "the bad pick (outside the list) is ignored"
                items = (await c.get(f"/api/rooms/{room['id']}/messages", params={"limit": 200})).json()[
                    "items"
                ]
                assert any("Reading for this run:" in m["body"]["text"] for m in items)
                [pick_msg] = [
                    m
                    for m in items
                    if m["sender"]["kind"] == "agent"
                    and (m["body"].get("data") or {}).get("step") == "select"
                ]
                assert "```files" not in pick_msg["body"]["text"], "the pick list is not shown in the chat"

                briefs = list((root / MEME / "briefs").glob("*.md"))
                outputs = list((root / MEME / "outputs").glob("*.md"))
                assert len(briefs) == 1 and "Retest H123 only." in briefs[0].read_text()
                assert "Approve the audit?" in briefs[0].read_text()
                assert len(outputs) == 1 and "author: Claude" in outputs[0].read_text()

                decision = (await c.get(f"/api/rooms/{room['id']}/decisions")).json()[0]
                ans = await c.post(
                    f"/api/decisions/{decision['id']}/answer", json={"answer": "decline", "note": "not now"}
                )
                assert ans.status_code == 200
                [saved] = list((root / MEME / "decisions").glob("*.md"))
                assert "answer: declined" in saved.read_text() and "not now" in saved.read_text()

                filed = await c.post(
                    "/api/workspace/inbox/file", json={"name": "meme-coin-ideas.md", "project_path": MEME}
                )
                assert filed.json()["path"] == f"{MEME}/notes/meme-coin-ideas.md"
                assert (await c.get("/api/workspace")).json()["inbox"] == []

                # Grok Bot: project card, read linked sources, save only to outputs.
                conn = await connect(c, room_ids=[room["id"]])
                async with mcp(srv, conn["token"]) as client:
                    proj: dict[str, Any] = await call(client, "get_project", room_id=room["id"])
                    assert proj["path"] == MEME and "Find an edge" in proj["card"]
                    files = await call(
                        client, "list_project_files", room_id=room["id"], path="sources/trading-review"
                    )
                    assert "HYPOTHESIS-REVIEW.md" in {f["name"] for f in files}
                    read = await call(
                        client,
                        "read_project_file",
                        room_id=room["id"],
                        path="sources/trading-review/HYPOTHESIS-REVIEW.md",
                    )
                    assert read["text"] == "H123 weak\n"
                    with pytest.raises(RuntimeError):
                        await call(client, "read_project_file", room_id=room["id"], path="../../../secret.md")
                    saved_out = await call(
                        client, "save_output", room_id=room["id"], title="Audit plan", text="Step 1."
                    )
                    assert saved_out["path"].startswith(f"{MEME}/outputs/")
                    assert "author: Grok Bot" in (root / saved_out["path"]).read_text()
                    with pytest.raises(RuntimeError):
                        await call(client, "get_project", room_id=general)  # not a member / not linked
