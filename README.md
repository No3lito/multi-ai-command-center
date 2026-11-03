# Multi-AI Command Center

A local-first, model-agnostic platform where Claude, ChatGPT, Grok, Gemini and locally hosted models collaborate as independent, interchangeable agents: chatting in shared rooms, delegating tasks, reviewing each other's work and building software together, under one human operator's control.

**Owner:** Noel Rodriguez
**Status:** Phase 2 in progress. Milestone A (dashboard, backend, database, persistent rooms, real-time messaging) is under review. See [`docs/status.md`](docs/status.md) for what works today.

## Quick start (Docker)

Requirements: Docker Desktop (macOS or Windows) or Docker Engine with the Compose plugin (Linux).

1. Clone the repo and create your settings file:

   ```sh
   git clone https://github.com/No3lito/multi-ai-command-center.git
   cd multi-ai-command-center
   cp .env.example .env
   ```

2. Open `.env` and set `OWNER_PASSWORD` (12+ characters) and `POSTGRES_PASSWORD` (letters and digits only). `openssl rand -hex 24` makes a good value for each.

3. Start everything:

   ```sh
   docker compose up --build
   ```

4. Open <http://localhost:8000> and sign in with your `OWNER_PASSWORD`.

The stack listens on `127.0.0.1` only. Your data lives in the `db-data` Docker volume and survives restarts; `docker compose down -v` deletes it.

## Development without Docker

Requirements: Python 3.12+, [uv](https://docs.astral.sh/uv/), Node.js 22, and PostgreSQL 16 (local install or any reachable server).

```sh
# Backend (http://localhost:8000)
cd backend
export DATABASE_URL=postgresql://USER:PASSWORD@localhost:5432/command_center
export OWNER_PASSWORD=choose-a-long-password
uv sync
uv run command-center migrate
# Allow the dev dashboard origin (:3000) in addition to the app itself
export ALLOWED_ORIGINS=http://localhost:8000,http://127.0.0.1:8000,http://localhost:3000,http://127.0.0.1:3000
uv run uvicorn command_center.main:app --reload --host 127.0.0.1 --port 8000 --no-proxy-headers

# Dashboard with hot reload (http://localhost:3000, proxies /api to :8000)
cd apps/web
npm install
NEXT_PUBLIC_WS_BASE=ws://localhost:8000 npm run dev
```

Or build the dashboard once (`npm run build` in `apps/web`) and the backend serves it at <http://localhost:8000>.

## Tests

| Suite | Command | Needs |
| --- | --- | --- |
| Backend (unit + integration, real PostgreSQL and a live server) | `cd backend && uv run pytest -q` | Local PostgreSQL binaries (a throwaway cluster is created) or `TEST_DATABASE_URL` |
| Dashboard unit tests | `cd apps/web && npm test` | Node 22 |
| Browser end-to-end | `cd tests/e2e && npm install && npx playwright test` | Built dashboard, Google Chrome, PostgreSQL as above |
| Lint and types | `make lint` | All of the above |

CI runs all of these on every push and pull request (`.github/workflows/ci.yml`).

## Repository map

| Path | What |
| --- | --- |
| `apps/web/` | Next.js dashboard (static export served by the backend) |
| `backend/command_center/` | FastAPI app, auth, messaging service, real-time hub |
| `backend/migrations/` | Alembic database migrations |
| `packages/protocol/` | CCMP v1 message schema shared by every participant |
| `docs/api/` | API contracts |
| `docs/phase-1-technical-discovery.md` | Approved architecture |
| `tests/e2e/` | Playwright browser tests |

## How code changes are made

Claude and ChatGPT work together on every change. One agent writes it on a branch and opens a pull request; the other reviews it and reports problems, and the author fixes them.

Nothing merges on its own. The owner approves each change with one click on the **Approve** button in the dashboard's Decisions panel. See [`docs/api/decisions.md`](docs/api/decisions.md).

## For AI collaborators

Read [`AGENTS.md`](AGENTS.md) first. Claude Code also reads [`CLAUDE.md`](CLAUDE.md).

## Roadmap

| Milestone | Scope | Status |
| --- | --- | --- |
| Phase 1 | Architecture (Revision 1) | Approved and merged |
| 2A | Dashboard, backend, database, persistent rooms, real-time messages | In review |
| 2B | Claude and OpenAI agents, coordinator, routing, usage and cost tracking | Next |
| 2C | Approvals, budgets, idempotent tools, emergency stop | Planned |
| 2D | Minimal authenticated MCP gateway for Claude Code and Gemini CLI | Planned |

## License

No license yet. All rights reserved by the owner until one is chosen.
