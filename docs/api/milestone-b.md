# API contract: Milestone B (live AI collaboration)

Extends [Milestone A](milestone-a.md); everything there still applies (auth, CSRF header, error shape, WebSocket stream).

## Concepts

- **Agent:** a principal of kind `agent` with a profile: role, provider, model, system prompt, output limit. Agents seeded by default, all members of `General`: **Claude** (Anthropic) and **GPT** (OpenAI) on first start, and **Grok** (xAI, `grok-4.20-0309-non-reasoning`) once, including on installs that existed before Grok was added.
- **Coordinator:** a principal of kind `system` named `Coordinator`. It posts `task.assign`, `task.status` and `task.result` messages that narrate runs.
- **Run:** one unit of coordinated work in a room. Two kinds:
  - `reply`: a single agent turn, created automatically when a chat message mentions an agent.
  - `collab`: the plan, critique, revise, summarize workflow between two agents.
  - `build`: design & build. Two co-designers with one goal (the owner gets exactly what they need) direct a builder, who follows their design exactly, including code-level instructions.
- **Provider mode** (`PROVIDER_MODE` setting):
  - `live` (default): agents call the real Anthropic, OpenAI or xAI API. A missing key makes the turn fail with a clear error message in the room. There is never a silent fallback.
  - `simulated`: every agent uses a deterministic local stand-in that costs nothing. Every simulated message carries `body.data.simulated = true` and the dashboard labels it **SIMULATED**.
- **Run tree:** every run belongs to a tree started by one human action. A `collab` run is the root of its own tree. The runs created by one human message share one tree; the first is the root. Runs that agent @mentions create join their parent's tree. `root_run_id` names the root.
- **Spending cap:** a persistent instance-wide cap on live spend (`LIVE_BUDGET_USD`, default `10.00`). Before every paid request the worst-case cost is reserved atomically: input tokens are estimated as one per UTF-8 byte of prompt (an upper bound for any language) plus the full output limit. The request is not sent if the reservation would exceed:
  - the instance cap (spent plus open reservations),
  - the run's own budget (spent plus its open reservations), or
  - the tree's budget, which is the root run's `budget_usd`, shared by every run in the tree (spent plus open reservations).
- **Settlement:** the actual cost replaces the reservation and is always recorded truthfully, even if it exceeds the estimate; new reservations are then refused. If the outcome is unknown (timeout, dropped connection, server error, or no usage report) the full reservation counts as spent. Each provider call has an overall timeout (`PROVIDER_CALL_TIMEOUT_SECONDS`, default `120`), and a timeout counts as billed.

## Message additions (CCMP v1, no schema change)

Agent and coordinator messages use the existing envelope:

| Field | Value |
| --- | --- |
| `sender.kind` | `agent` or `system` |
| `kind` | `chat` (agent replies), `task.assign`, `task.status`, `task.result`, `error` |
| `correlation_id` | the run id (`run_...`) |
| `reply_to` | the message being answered |
| `usage` | `{input_tokens, output_tokens, cost_usd}` on agent messages |
| `body.data` | `{run_id, step, provider, model, simulated}` on agent messages; `{run_id, status}` on coordinator messages |

## Agents

| Method | Path | Body | Response |
| --- | --- | --- | --- |
| GET | `/api/agents` | none | `200 Agent[]` |
| POST | `/api/agents` | `AgentIn` | `201 Agent`; `409 agent_exists`; `422` |
| PATCH | `/api/agents/{agent_id}` | partial `AgentIn` | `200 Agent` |
| POST | `/api/rooms/{room_id}/members` | `{"principal_id": "agt_..."}` | `200 RoomDetail` (agents only; idempotent) |

`AgentIn`: `{"display_name": "Claude", "role": "Planner", "provider": "anthropic" | "openai" | "xai" | "simulated", "model": "claude-sonnet-5-5", "system_prompt": "...", "max_output_tokens": 2048, "enabled": true}`

`Agent`: `AgentIn` plus `{"id": "agt_...", "kind": "agent", "status": "live" | "simulated" | "missing_key" | "unknown_price" | "disabled", "price": {"input_per_mtok": 2.0, "output_per_mtok": 10.0} | null}`

`status` tells the dashboard whether the agent can run right now:

| Status | Meaning |
| --- | --- |
| `live` | Key configured and price known |
| `simulated` | `PROVIDER_MODE=simulated` or provider `simulated` |
| `missing_key` | No API key for that provider |
| `unknown_price` | The model has no price in the price table, so live calls are blocked |
| `disabled` | The agent is turned off |

## Runs

| Method | Path | Body | Response |
| --- | --- | --- | --- |
| POST | `/api/rooms/{room_id}/runs` | `{"goal": "Create a basic login interface", "planner_id": "agt_...", "critic_id": "agt_...", "budget_usd": 0.50, "max_turns": 8}` | `201 Run` |
| GET | `/api/rooms/{room_id}/runs?limit=20` | none | `200 Run[]` newest first |
| GET | `/api/runs/{run_id}` | none | `200 Run` |
| POST | `/api/runs/{run_id}/cancel` | none | `200 Run`. Cancels this run and every unfinished run in its tree; a cancelled tree gets no new runs. No-op if already finished. |

`budget_usd` defaults to `0.50` (maximum `5.00`), and `max_turns` defaults to `8` (maximum `20`). Planner and critic must be different agents and members of the room.

For design & build, send `"workflow": "build"` and a `builder_id`: `planner_id` is the designer, `critic_id` the co-designer and `builder_id` the builder, all different enabled agents in the room. A build run gets at least 7 turns.

`Run`:

```json
{
  "id": "run_...", "room_id": "room_...", "kind": "collab" | "reply",
  "status": "queued" | "running" | "completed" | "failed" | "cancelled" | "budget_exceeded",
  "goal": "...", "step": "plan" | "critique" | "revise" | "summary" | "reply" | "done",
  "planner_id": "agt_..." | null, "critic_id": "agt_..." | null, "agent_id": "agt_..." | null,
  "root_run_id": "run_...",
  "turn_count": 2, "max_turns": 8,
  "budget_usd": 0.5, "spent_usd": 0.0123,
  "simulated": false, "error": null,
  "created_at": "...", "updated_at": "...", "finished_at": null
}
```

### Collab workflow

`plan` (planner) → `critique` (critic) → `revise` (planner) → `summary` (coordinator, no model call) → `done`.

The coordinator posts a `task.assign` message before each agent step and a `task.result` summary at the end. Each step's message replies to the previous one. A step that fails (provider error, budget) ends the run with `failed` or `budget_exceeded` and an `error` message in the room. Approval gates arrive in Milestone C.

### Design & build workflow (`kind: "build"`)

| Step | Agent | What it does | Output limit |
| --- | --- | --- | --- |
| `design` | designer | Drafts the design: what, structure and files, key decisions, how to verify; code-level instructions where they matter | agent's own |
| `codesign` | co-designer | Improves it as an equal partner; says what changed and why | agent's own |
| `feasibility` | builder | Minor input: under 120 words on what would block the build, or "ready" | 400 tokens |
| `finalize` | designer | The final specification both designers agree on | agent's own |
| `build` | builder | Implements the final design exactly: every file in full, then how to run it | 8,192 tokens |
| `check` | co-designer | `APPROVED` as the first word, or numbered fix instructions | agent's own |
| `fix` | builder | Skipped when approved; otherwise applies the instructions exactly and outputs changed files | 8,192 tokens |
| `summary` | coordinator | Says where the code is and the real cost | none |

Messages of the run itself are kept nearly whole in each agent's context (up to 40,000 characters each, 80,000 in total), so the builder sees the whole design and the checker sees the whole build. Older room messages keep the usual limits.

For now the builder writes code into the room. Saving files and running code need the execution sandbox and approval gates (Milestone C and later).

### Mention routing

When a chat message mentions an agent that is a member of the room, a `reply` run is created for each mentioned agent (at most 5 per message). That agent answers with `reply_to` set to the message.

An agent reply can itself mention other agents, which creates further runs in the same tree. Limits, all enforced before any paid call:

- at most 3 agent hops from the human message;
- at most `MAX_RUNS_PER_TREE` runs per tree (default `10`); further mentions are ignored;
- one shared budget per tree: `0.50` USD for a tree started by a chat message (each reply run also has its own `0.25` limit), or the collab run's `budget_usd`.

A run that has already finished (for example cancelled) never changes status again. If a step's answer was already posted before a crash, the step reuses it instead of calling the model again.

## Usage

`GET /api/usage`:

```json
{
  "cap_usd": 10.0, "spent_usd": 0.42, "reserved_usd": 0.01, "remaining_usd": 9.57,
  "by_provider": [{"provider": "anthropic", "model": "claude-sonnet-5-5", "calls": 3, "input_tokens": 1200, "output_tokens": 900, "cost_usd": 0.0114, "simulated": false}],
  "simulated_calls": 12
}
```

Simulated calls are counted separately and never touch the cap.

## Real-time

No new socket. Agent and coordinator messages arrive on the room stream like any other message. The dashboard refreshes run status by fetching `GET /api/runs/{id}` (or the room's run list) whenever a message with that `correlation_id` arrives.

## xAI (Grok) notes

Checked Nov 2, 2026 against [docs.x.ai](https://docs.x.ai/docs/guides/chat) and [xAI models and pricing](https://docs.x.ai/developers/models):

- Grok is called through xAI's Responses API at `https://api.x.ai/v1` with the official OpenAI SDK, which xAI documents as its preferred API. `store=false` is sent, as for OpenAI.
- xAI does not document `instructions`, so the system prompt is sent as a `system` message.
- xAI lists reasoning tokens as a separately billed token type without saying whether `output_tokens` includes them. The app adds `reasoning_tokens` to output tokens, which can only over-count. Compare with the xAI console after real use.
- The default model is non-reasoning, so its cost is bounded by `max_output_tokens`. A reasoning model such as `grok-4.7` may produce reasoning beyond that limit; any overrun is recorded truthfully and blocks further calls once the cap is reached.
- From 200k prompt tokens, xAI's higher rate applies to all tokens of the request; the price table models this.
