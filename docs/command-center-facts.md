# Command Center facts (for agents)

Updated with every merged change. Read this before planning work on the Command Center itself. **Verified** means checked in the code at the time of writing.

## What can actually do work
- **Claude and GPT** (model agents) read the conversation and attached files and write text: plans, reviews, specs, and code as text. **They cannot run code, open the repository, change files or merge anything.**
- **Grok Bot** (connected over MCP) works with its own tools and files, reads the room's project folder, and saves to its `outputs/`. **It cannot change the Command Center's code.**
- **Grok** (xAI model agent) is like Claude and GPT: text only. It has no API key on this install, so it is unavailable.
- **Changing the Command Center's code** needs a coding agent with repository access, for example Claude Code or OpenAI Codex, working on a branch. Noel approves every merge. Never plan as if a builder in the room will apply code.

## Code layout (verified)
- Dashboard: `apps/web/src/components` (React components), `apps/web/src/lib` (API client, hooks, types). Next.js static export, served by the backend.
- Backend: `backend/command_center` (FastAPI app, `routes_b.py` for agents, runs, decisions and workspace; `orchestrator/engine.py` for workflow steps; `decisions.py`; `workspace.py`; `mcp_gateway.py`). Migrations: `backend/migrations/versions`.
- Tests: `backend/tests` (pytest, real PostgreSQL and fake providers), Vitest next to components (`*.test.tsx`), Playwright in `tests/e2e`.

## Versions (verified, apps/web/package.json and tests/e2e/package.json)
next 16.4.4 · react 19.3.1 · tailwindcss 4.3.3 · vitest 5.1.0 · @playwright/test 1.63.0. react-markdown 10.1.0 and remark-gfm 4.0.1 (exact) render chat messages: no raw HTML, safe links only.

## Behavior worth knowing (verified)
- **Senders** are `{principal_id, kind, display_name}` with kind `owner`, `agent`, `external` or `system` (the Coordinator). For agents, the provider is on `/api/agents`, not on messages.
- **Answering a decision** locks the decision row, so two clicks give one 200 and one 409, and start at most one follow-up run.
- **`GET /api/runs/{id}`** exists. Runs have no client-supplied idempotency key.
- **Follow-ups:**
  - At most 2 rounds per topic. The last round must conclude.
  - They share a $2.00 budget per chain, and a dollar cap written in the owner's note is enforced.
  - They carry forward only the previous brief and its final message.
- **Briefs** start with `**Verdict:** Done | Blocked | Needs you`.

## Status
- Merged to main: Milestone B, the Grok builder, the Grok Bot bridge, files and briefs, and decision cards (PR #8).
- In review: PR #9 (self-serve dashboard), PR #10 (project workspace), PR #11 (conclude, don't loop) and the dashboard redesign.
- New rooms include every agent that can answer (Claude and GPT). The "collab" workflow is labeled **Collaborate** on the dashboard.
