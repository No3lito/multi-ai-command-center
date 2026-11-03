# Project status

Updated Nov 2, 2026. This file is the single place to see what works, what was tested, and what is blocked.

## Decision cards (in review, branch `agent/claude/decision-cards`)

- Every "Waiting on you" item in a brief becomes a card on the dashboard, with **Approve**, **Need more info**, **Decline** and **Dismiss** buttons, an optional note, and a budget.
- Approving (or asking for more info) starts the follow-up run the agents already prepared, at once. Grok Bot sees every answer in the room and through the new `get_decisions` MCP tool.

Contract: [`docs/api/decisions.md`](api/decisions.md).

Evidence:

- Backend (fake providers): block parsing, storing decisions, fallback from bullets, worker fallback, and the full API flow. That flow covers approve with a note and budget, a follow-up run that completes, decline, answering twice (409), sign-in required (401), and Coordinator messages.
- Dashboard tests for the cards and the hook.
- A simulated browser test that approves a card.

**Not yet verified with real models.**

## Attached files and decision briefs (merged in PR #7)

- **Attached files:** Claude and GPT can read owner-chosen files from one folder, mounted read-only. Files are snapshotted when a run starts.
- **Decision briefs:** every run ends with a fixed-format brief (bottom line, decided, done, waiting on you, next steps, open risks). A Decisions panel shows the latest conclusion and the open decisions.

Contract: [`docs/api/files-and-briefs.md`](api/files-and-briefs.md).

Evidence:

- Backend: path safety (traversal, hidden files, links out, binary), snapshot freezing, prompt contents with the fake providers, brief parsing and storage.
- Dashboard tests, and a browser test that sees the brief in the Decisions panel.

**Verified by the owner (Nov 2, 2026, 8:36 PM ET):**

- A real Plan & review run (Claude Sonnet 5.5 and GPT-6.1 Sol) read two attached files from the owner's Trading-Review folder: `HYPOTHESIS-REVIEW.md` and `FROZEN-SPECS-2026-11-02.md`.
- It checked them against the agreed plan.
- It ended with a decision brief. The Decisions panel showed the bottom line and three "Waiting on you" items.

## Grok Bot bridge (merged in PR #6)

The owner's Grok Bot (xAI's hosted agent app, with its own sub-agents and work) joins the Command Center over MCP. Its first job is a **Review & improve** run: Grok Bot shares its work, Claude and GPT review it and write a plan of fixes and new ideas, and Grok Bot responds. Contract and setup: [`docs/api/bridge.md`](api/bridge.md).

Evidence so far:

- `backend/tests/test_bridge.py`: an official MCP SDK client against the real server. It covers tokens, room scoping, rate limits, rotation and revocation, and a full review run with fake Claude and GPT providers. It also checks cancelling and timeouts.
- Dashboard tests and a browser test: connect Grok Bot, then a review that waits for it.

**Verified by the owner (Nov 2, 2026):**

- A named Cloudflare Tunnel (`command-center`, running as a Windows service on the Docker computer) routes `grokbot.multiaicommandcenter.com` to the gateway on port 8001 only.
- From the internet, `/mcp` answers "only POST is supported" and `/` answers "not found". The dashboard is not reachable.
- The owner's real Grok Bot added the server and called `whoami`, which returned the name Grok Bot and the room Meme Coin Strategy.

**First real review completed (Nov 2, 2026, 8:07 PM ET):** Grok Bot shared its 112-hypothesis meme-coin research log over MCP. Claude Sonnet 5.5 reviewed it, GPT-6.1 Sol challenged the review (and corrected two of Claude's errors), and Claude wrote an 8-step plan. Grok Bot responded, saved `HYPOTHESIS-REVIEW.md` and a dated `CLAUDE-FEEDBACK.md` note on the owner's computer, and held every paid-data step for the owner's approval. Real API cost: $0.1452.

Found and fixed during the first attempts:

- Claude 5.5's thinking used up the 2,048-token output limit. Claude now runs at medium effort, with 12,000 tokens for review and design steps.
- Run summaries repeated very long goals. They now show the goal's first line.

## Grok agent and design & build workflow (merged in PR #5)

Branch: `agent/claude/grok-agent`.

- **Grok (xAI)** is a third agent with the role Builder, on `grok-build-0.1`. It is seeded once on existing installs and sits behind the same spending cap.
- **Design & build:** following the owner's direction, Claude and GPT are equal co-designers with one goal. Grok follows their design exactly, including code, and adds only minor input. GPT checks the build, and Grok applies any fixes.

Evidence:

- Mocked adapter tests.
- Fake-provider runs of the full workflow: `backend/tests/test_grok.py` and `test_build_workflow.py`.
- A simulated browser test.
- **Real xAI API: pending the owner's `XAI_API_KEY`.**

## Milestone B: live AI collaboration (accepted, merged in PR #4) Contract: [`docs/api/milestone-b.md`](api/milestone-b.md).

### Evidence labels

- **Simulated:** `PROVIDER_MODE=simulated`, deterministic stand-ins, no network, no cost. Proves workflow and UI.
- **Fake provider:** the full live code path (keys, official Anthropic and OpenAI SDKs, HTTP, cost accounting, spending cap) against a local fake server that imitates both APIs. Proves the plumbing and the money logic, **not** the real APIs.
- **Real API:** run by the owner on his machine with his own keys (see "Real API verification" below).

### What works

| Feature | Evidence |
| --- | --- |
| Claude (Anthropic Messages API) and GPT (OpenAI Responses API, `store=false`) agents as separate participants with their own identities, roles and models | Fake provider: `test_providers_mocked.py`, `test_live_code_path_with_fake_providers` |
| Coordinator runs plan, critique, revise, summary between two agents, narrated in the room | Simulated and fake provider: `test_coordinator.py`; browser: `tests/e2e/milestone-b.spec.ts` |
| @mention routing: agents answer human messages and can address each other | Simulated: `test_mention_creates_reply`; fake provider: `test_review_fixes.py` |
| $10 live cap enforced before every paid request: worst-case reservation, run and run-tree budgets, concurrency-safe, true spend recorded | Fake adapter: `test_budget.py`, `test_review_fixes.py` |
| Missing keys fail loudly; no silent fallback to simulated answers | `test_live_mode_without_keys_fails_loudly` |
| Usage and cost per provider and model, simulated calls counted separately | `test_coordinator.py`, dashboard Usage panel |
| `command-center live-check`: one tiny real call per provider through the cap | Fake provider: `test_live_check_command_with_fake_providers`. **Real API: verified by the owner** |
| Durable runs: Postgres lease with heartbeat, survive restarts, cancel stops a whole run tree | `test_review_fixes.py`, `test_cancel_during_model_call` |

Screenshot (simulated): [`docs/screenshots/milestone-b-simulated-run.png`](screenshots/milestone-b-simulated-run.png)

### Test results (latest run)

| Suite | Result |
| --- | --- |
| Backend: pytest against real PostgreSQL 16, live servers and fake providers | 95 passed, 3 consecutive runs |
| Backend: ruff lint and format, mypy strict | clean |
| Dashboard: Vitest; TypeScript; production build | 78 passed; clean |
| Browser end-to-end: Playwright in Chrome (simulated mode) | 3 passed |

### Real API verification (Nov 2, 2026, owner's Windows machine, Docker)

| Check | Result |
| --- | --- |
| `command-center live-check` | Anthropic `claude-haiku-5-5` and OpenAI `gpt-6-luna` both answered `OK`; $0.000015 recorded against the $10 cap |
| Real collaboration ("Create a basic login interface", Claude plans, GPT reviews) | Completed with real Claude Sonnet 5.5 and GPT-6.1 Sol answers; the run cost $0.0305. Total real spend so far: $0.0658 of $10 |

The first real run found three problems, now fixed with tests:

| Problem | Fix |
| --- | --- |
| A collaboration's @mentions also started reply runs, so Claude answered twice in parallel and agents kept replying after the summary | Only free conversation (reply runs) spawns replies; a collaboration speaks strictly in turn |
| 1024 output tokens cut Claude's plans off mid-sentence | Default raised to 2048 (migration 0004 moves agents still on 1024); any cut-off answer is now labeled as cut off |
| The goal was not visible in the room, so agents doubted it came from the owner | Step 1 now names the goal |

A new test also exposed a database deadlock when two runs in one tree reserved and settled at the same moment; lock order is now the same everywhere.

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
| Milestone B sign-off | Review PR #4 and approve the merge |

## Next: Milestone C

Approvals, emergency stop, idempotency and budget controls in the dashboard, more tests.
