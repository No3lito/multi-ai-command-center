# API contract: Milestone B (live AI collaboration)

Extends [Milestone A](milestone-a.md); everything there still applies (auth, CSRF header, error shape, WebSocket stream).

## Concepts

- **Agent:** a principal of kind `agent` with a profile: role, provider, model, system prompt, output limit. Two agents are seeded on first start: **Claude** (Anthropic) and **GPT** (OpenAI), both members of `General`.
- **Coordinator:** a principal of kind `system` named `Coordinator`. It posts `task.assign`, `task.status` and `task.result` messages that narrate runs.
- **Run:** one unit of coordinated work in a room. Two kinds:
  - `reply`: a single agent turn, created automatically when a chat message mentions an agent.
  - `collab`: the plan, critique, revise, summarize workflow between two agents.
- **Provider mode** (`PROVIDER_MODE` setting):
  - `live` (default): agents call the real Anthropic or OpenAI API. A missing key makes the turn fail with a clear error message in the room. There is never a silent fallback.
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

`AgentIn`: `{"display_name": "Claude", "role": "Planner", "provider": "anthropic" | "openai" | "simulated", "model": "claude-sonnet-5-5", "system_prompt": "...", "max_output_tokens": 1024, "enabled": true}`

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
