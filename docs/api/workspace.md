# Project workspace

The owner's work lives in one folder, the workspace (for example `C:\Users\noelm\Multi-AI-Command-Center-Workspace`), which is also an Obsidian vault. Each room in the Command Center is linked to a project folder. Agents read the project themselves, and every run's results are saved back into it.

## Layout

```
00-INBOX/                         anything new; filed into a project with one click
01-PROJECTS/<family>/<project>/
  PROJECT.md                      goal, status, next, rules, where files are (YAML front matter)
  sources/<name>/                 the owner's live folders, linked read-only (Windows junctions)
  briefs/ decisions/ outputs/ notes/   written by the Command Center
01-PROJECTS/<family>/<FAMILY>.md  shared rules and lessons for the family
02-REFERENCE/owner-rules.md       standing rules every run reads
09-ARCHIVE/                       finished or paused projects
10-SYSTEM/INDEX.md                map of every project (the table between the markers is generated)
10-SYSTEM/AGENTS.md               how agents work in the workspace
10-SYSTEM/links.json              {"links": [{"project", "name", "target"}]}: the linked folders
10-SYSTEM/link-sources.ps1        creates the junctions from links.json
```

## Setup (Docker)

1. In `.env`, set `FILES_FOLDER` to the workspace. It's mounted at `/shared`, and the app may write to it, but only as listed below.
2. Run `infrastructure\workspace-mounts.ps1`. It reads `links.json` and writes `docker-compose.override.yml` (gitignored), with one **read-only** mount per linked folder at `/sources/<project with / as __>__<name>`. Docker can't follow Windows junctions, so this is how linked folders reach the container.
3. Run `docker compose up -d`. Run steps 2 and 3 again whenever `links.json` changes.

## What the Command Center may write

**It writes only:**
- new files in a project's `briefs/`, `decisions/`, `outputs/` and `notes/` (never overwriting);
- new project skeletons;
- the generated table in `INDEX.md`;
- moves of files from `00-INBOX` into a project's `notes/`, on the owner's click.

**It never:**
- writes into `sources/`;
- deletes anything;
- reads outside the workspace or a linked folder. `..`, absolute paths, hidden files and links pointing elsewhere are refused.

## Runs in a project room

- **New first step, `select`:**
  - The project card, the family page and `02-REFERENCE/owner-rules.md` are attached.
  - If `agent_files` is true (the default), the lead agent sees the list of readable files and picks up to 8. Picks outside that list are ignored. The list skips `node_modules`, `.git`, `logs`, `raw`, `worldmonitor-ref` and `*.bak*`.
  - Picked files are snapshotted, within the usual 10-file and 300,000-character limits. A Coordinator note says what is being read.
  - This costs one extra turn, so `max_turns` gets +1.
- **When the brief is written:**
  - The brief is saved to `briefs/`.
  - The last work message before the brief is saved to `outputs/`.
- **When a decision is answered:** the answer is saved to `decisions/`.
- Saving is best effort and never fails a run.

## API (owner session)

- `GET /api/workspace` returns `{enabled, structured, families, projects: [{path, family, slug, title, status, goal}], inbox: [{name, size, suggested_project}]}`.
  - `suggested_project` is a free keyword match; no AI is called.
- `POST /api/workspace/projects` with `{family, name, goal?}` creates a project and returns `ProjectOut` (201).
- `POST /api/rooms` takes an optional `project_path` (link an existing project) or `new_project: {family, name, goal?}` (create one), but not both.
- `PUT /api/rooms/{id}/project` with `{project_path | null}` links or unlinks a room.
- `POST /api/workspace/inbox/file` with `{name, project_path}` moves an inbox file to `<project>/notes/`.
- `GET /api/rooms/{id}/suggest-files?goal=` returns `{project_path, always, suggested: [{path, size, matched}]}`.
  - `always` lists what every run attaches: the project card, the family page and the owner's rules.
  - `suggested` holds up to 6 files whose names (weight 3) or first 4 KB (weight 1) match the goal's words; common words are ignored.
  - No AI is called. The New goal form pre-checks these as the owner types, the owner removes or adds files, and the lead agent can still pick more when the run starts.
- `GET /api/files?path=` browses the workspace, including linked sources. Attachments take workspace paths.
- `RoomOut.project_path`, `RunCreateIn.agent_files` and `RunOut.agent_files` are new fields.

## MCP tools for external agents (Grok Bot)

These work only in rooms the agent belongs to that are linked to a project.

- `get_project(room_id)` returns the card, the linked source folders, and where the agent may write.
- `list_project_files(room_id, path)` and `read_project_file(room_id, path)`: `path` is relative to the project. Reads are capped at 200,000 characters.
- `save_output(room_id, title, text)` writes a new file in `outputs/`, up to 64,000 characters, counted against the hourly volume quota.

## Never in the workspace

Healthcare work (Pathways, MSO, American Health Intel, ACO-OS, HCC reports), passwords, API keys, tokens, wallet keys and app settings. Everything Claude and GPT read is sent to Anthropic and OpenAI.
