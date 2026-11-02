# Project status

Updated Nov 2, 2026. This file is the single place to see what works, what was tested, and what is blocked.

## Milestone B: live AI collaboration (in review)

Branch: `agent/claude/milestone-b`, draft PR #4. Not merged until the owner approves. Contract: [`docs/api/milestone-b.md`](api/milestone-b.md).

### Evidence labels

- **Simulated:** `PROVIDER_MODE=simulated`, deterministic stand-ins, no network, no cost. Proves workflow and UI.
- **Fake provider:** the full live code path (keys, official Anthropic and OpenAI SDKs, HTTP, cost accounting, spending cap) against a local fake server that imitates both APIs. Proves the plumbing and the money logic, **not** the real APIs.
- **Real API:** not yet run. Needs the owner's keys; see below.

### What works

| Feature | Evidence |
| --- | --- |
| Claude (Anthropic Messages API) and GPT (OpenAI Responses API, `store=false`) agents as separate participants with their own identities, roles and models | Fake provider: `test_providers_mocked.py`, `test_live_code_path_with_fake_providers` |
| Coordinator runs plan, critique, revise, summary between two agents, narrated in the room | Simulated and fake provider: `test_coordinator.py`; browser: `tests/e2e/milestone-b.spec.ts` |
| @mention routing: agents answer human messages and can address each other | Simulated: `test_mention_creates_reply`; fake provider: `test_review_fixes.py` |
| $10 live cap enforced before every paid request: worst-case reservation, run and run-tree budgets, concurrency-safe, true spend recorded | Fake adapter: `test_budget.py`, `test_review_fixes.py` |
| Missing keys fail loudly; no silent fallback to simulated answers | `test_live_mode_without_keys_fails_loudly` |
| Usage and cost per provider and model, simulated calls counted separately | `test_coordinator.py`, dashboard Usage panel |
| `command-center live-check`: one tiny real call per provider through the cap | Fake provider: `test_live_check_command_with_fake_providers`. Real API: pending keys |
| Durable runs: Postgres lease with heartbeat, survive restarts, cancel stops a whole run tree | `test_review_fixes.py`, `test_cancel_during_model_call` |

Screenshot (simulated): [`docs/screenshots/milestone-b-simulated-run.png`](screenshots/milestone-b-simulated-run.png)

### Test results (latest run)

| Suite | Result |
| --- | --- |
| Backend: pytest against real PostgreSQL 16, live servers and fake providers | 93 passed |
| Backend: ruff lint and format, mypy strict | clean |
| Dashboard: Vitest; TypeScript; production build | 78 passed; clean |
| Browser end-to-end: Playwright in Chrome (simulated mode) | 3 passed |

### Independent security review

No critical findings. Every must-fix item is fixed with a regression test in `backend/tests/test_review_fixes.py`:

| # | Severity | Finding | Fix |
| --- | --- | --- | --- |
| 1 | High | Agents mentioning each other could fan one message out to 155 paid calls | Runs form trees: at most 10 runs (`MAX_RUNS_PER_TREE`) and one shared budget per tree ($0.50 for a chat message); cancel stops the whole tree |
| 2 | Medium | Token estimate (characters / 2.5) undercounted emoji and non-Latin text | One token per UTF-8 byte, an upper bound for any text |
| 3 | Medium | Spend above the estimate was clamped to the cap | True amount always recorded; further calls refused |
| 4 | Medium | No overall call timeout; lease could expire during a slow step; run budget ignored in-flight reservations | 120 s overall timeout counted as billed; lease heartbeat; budgets include open reservations |
| 5 | Medium | `PATCH /api/agents` with `null` returned 500 | `null` means unchanged |

Low items also fixed: finished runs never change status, missing usage is billed at the worst case, a step already answered before a crash is not paid for twice, transcript lines are JSON so message text cannot impersonate another speaker, a warning when a provider base URL is overridden, and stale reservations are swept every 5 minutes.

## Milestone A: foundation (accepted, merged in PR #3)

### What works

| Feature | Evidence |
| --- | --- |
| Owner sign-in with server-side sessions (HttpOnly, SameSite=Strict cookie; 12-hour expiry; logout revokes) | `backend/tests/test_auth.py` |
| Persistent rooms: list, create (unique, case-insensitive), details with members; default `General` room | `test_rooms_messages.py` |
| Persistent CCMP v1 messages, validated against `packages/protocol/ccmp.schema.json` | `test_message_is_valid_ccmp_and_persisted` |
| Gap-free per-room ordering under 40 concurrent posts; independent sequences per room | `test_seq_is_gap_free_under_concurrency` |
| Idempotent posting: retries and 10 simultaneous duplicates create exactly one message | `test_concurrent_duplicate_submissions_create_one_message` |
| Live updates over WebSocket: replay after `after_seq`, then live delivery in under 1 second; fan-out to every open tab; room isolation; heartbeats | `test_realtime.py` |
| Delivery survives loss of the database notification connection | `test_delivery_survives_listener_connection_loss` |
| Messages persist across a server restart | `test_messages_persist_across_server_restart` |
| Dashboard: sign-in, three-pane chat, room creation, live updates without refresh, reconnect with catch-up and no duplicates, light and dark themes, phone layout | `apps/web` unit tests; `tests/e2e/milestone-a.spec.ts` in Chrome |
| Security hardening from the independent review (see below) | `backend/tests/test_security.py` |
| One-command startup with Docker Compose, published on 127.0.0.1 only | Verified by the owner on Windows (see below) |

Screenshots: [`docs/screenshots/milestone-a-dashboard.png`](screenshots/milestone-a-dashboard.png), [`docs/screenshots/milestone-a-mobile.png`](screenshots/milestone-a-mobile.png)

### Test results (latest run)

| Suite | Result |
| --- | --- |
| Backend: pytest against real PostgreSQL 16 and a live server | 48 passed, 3 consecutive runs |
| Backend: ruff lint and format, mypy strict | clean |
| Dashboard: Vitest | 35 passed |
| Dashboard: ESLint, TypeScript, production build | clean |
| Browser end-to-end: Playwright in Google Chrome | 2 passed |
| GitHub Actions CI (backend, web, e2e jobs) | passing on the branch |

### Independent security review

A separate reviewer audited the backend and container setup. No critical or high findings. All 10 "must fix" items are fixed with regression tests:

| # | Severity | Finding | Fix |
| --- | --- | --- | --- |
| 1 | Medium | Live stream kept working after logout or session expiry | Streams re-check the session on every wake-up; logout closes them immediately |
| 2 | Medium | Dashboard dev server listened on all network interfaces | Bound to 127.0.0.1 |
| 3 | Medium | `.env` files in subfolders could be copied into the Docker image | `**/.env` patterns in `.dockerignore` |
| 4 | Medium | No request size limit; unbounded `mentions` | 128 KB body limit (413); mentions must be principal ids; container memory and process limits |
| 5 | Low | Spoofed `X-Forwarded-For` bypassed the login rate limit | Proxy headers ignored everywhere |
| 6 | Low | Default allowed origins trusted port 3000 | Default is the app's own origin only |
| 7 | Low | Huge `after_seq` caused a 500 and logged SQL | Range checked (422 or close code 4400) |
| 8 | Low | A too-short password was echoed in the startup error | Inputs hidden in configuration errors |
| 9 | Low | Concurrent key reuse across rooms could return another room's message | Room checked on the race path (also fixed a related async bug found by the new test) |
| 10 | Low | Binary WebSocket frame caused an uncaught error | Non-text frames ignored |

Also closed now: Host header allowlist (DNS-rebinding guard), API docs off by default, rate limiter memory bounded.

Tracked for later milestones: session table cleanup, WebSocket connection caps, masking message text in database error logs, image digest pinning and Docker secrets, validating `reply_to` and `mentions` against real messages and members (needed once agents join in Milestone B).

### Owner verification (Nov 2, 2026)

Verified by the owner on Windows with Docker Desktop 29.9.2 (WSL 2): `docker compose up --build` built and started both containers, the database initialized, health checks passed, sign-in worked at http://localhost:8000, a message persisted, and messages appeared live in two browser tabs without refreshing.

## What the owner needs to provide

| For | Item |
| --- | --- |
| Milestone B real-API verification | Anthropic and OpenAI API keys, added only to your local `.env` (never pasted into chat or committed). Budget: $10 total, enforced in code before every paid call |
| Milestone B sign-off | Review PR #4 and approve the merge |

## Next: Milestone C

Approvals, emergency stop, idempotency and budget controls in the dashboard, more tests.
