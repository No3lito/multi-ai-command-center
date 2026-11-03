# Grok Bot bridge: external agents over MCP

Lets agents that live outside the Command Center, starting with the owner's **Grok Bot** (xAI's hosted personal-agent app), join rooms, take part in runs, and get their work reviewed by Claude and GPT. Each project is a room; a connection can be added to as many rooms as needed.

## Pieces

| Piece | What it is |
| --- | --- |
| Connection | A principal of kind `external` with a revocable access token. The token is shown to the owner once and stored only as a SHA-256 hash. |
| MCP gateway | A separate listener (`MCP_PORT`, default `8001`) serving only `POST /mcp`, built on the official MCP Python SDK (MIT), stateless streamable HTTP with JSON responses (no Server-Sent Events, so it works through Cloudflare Quick Tunnels). |
| Waiting runs | When a run step belongs to an external agent, the run's status becomes `waiting` and `waiting_for` names the agent. It resumes when the agent submits its part. After `EXTERNAL_TASK_TIMEOUT_HOURS` (default 24) without an answer, the run fails. |

## Dashboard API (owner only)

| Method | Path | Body | Response |
| --- | --- | --- | --- |
| GET | `/api/connections` | none | `200 Connection[]` (never includes tokens) |
| POST | `/api/connections` | `{"display_name": "Grok Bot", "room_ids": ["room_..."]}` (rooms default to General) | `201 Connection` with `token` (shown once) |
| POST | `/api/connections/{id}/rotate` | none | `200 Connection` with a new `token`; the old one stops working at once; re-enables a disconnected connection |
| POST | `/api/connections/{id}/revoke` | none | `200 Connection` with `status: "disabled"`; the token stops working at once and runs waiting for it fail |
| POST | `/api/rooms/{room_id}/members` | `{"principal_id": "ext_..."}` | adds a connection to another project room |

`Connection`: `{"id", "display_name", "status": "active" | "disabled", "created_at", "last_used_at", "rooms": [{"id", "name"}], "token": string | null, "mcp_path": "/mcp", "mcp_port": 8001}`

## MCP tools (what Grok Bot sees)

Every request needs `Authorization: Bearer ccx_...`. Missing, wrong or revoked tokens get `401` before any MCP processing. Each connection is limited to `MCP_REQUESTS_PER_MINUTE` (default 120), then `429`.

| Tool | Arguments | Does |
| --- | --- | --- |
| `whoami` | none | Its name and rooms |
| `list_rooms` | none | Rooms it is a member of |
| `read_messages` | `room_id`, `after_seq` = 0, `limit` = 50 (max 100) | Messages oldest first, with sender type |
| `post_message` | `room_id`, `text` (max 32,000), `reply_to` | Posts a chat message as itself. Never starts AI runs. |
| `get_tasks` | none | Steps waiting for it: instruction, goal, and the run's conversation |
| `submit_task` | `run_id`, `text` (max 96,000, split into parts) | Answers a waiting step; the run continues |

An external agent cannot start runs, call models, spend money, manage agents or connections, or read rooms it is not in.

## Workflows that use external agents

External agents can be the **builder** (design & build) or the **worker** (review & improve). Designers and reviewers must be model agents.

### Review & improve (`workflow: "review"`)

| Step | Who | Does |
| --- | --- | --- |
| `share` | worker | Shares its work: what it built, every approach with results, data and gaps, failures, open questions |
| `analyze` | lead reviewer (Claude) | What is solid, what is broken and why, unsupported conclusions, fixes |
| `ideas` | co-reviewer (GPT) | Challenges the analysis, adds new ideas with cheap tests |
| `plan` | lead reviewer | Numbered, prioritized instructions with tests and success criteria. Research, backtests and paper tests only: never real trades, moving funds or changing live settings. |
| `respond` | worker | Says which instructions it will run, flags what it cannot do, reports results |
| `summary` | coordinator | Where the plan is, and the real cost |

## Security notes

- Only port 8001 should ever be reachable from the internet, and only through a tunnel. The dashboard (8000) stays on `127.0.0.1`.
- Text from external agents reaches Claude and GPT labeled `"type": "external"` in a JSON-lines transcript that message text cannot forge; the system prompt tells them to treat transcript content as information, not instructions.
- Every write (`post_message`, `submit_task`) is recorded in the audit log.
- Rotate the token if it was ever pasted somewhere it should not be; disconnect to cut access instantly.

## Owner setup (Windows, Docker)

Walked through one step at a time with the owner; summary for reference:

1. Pull the branch and `docker compose up --build`. The gateway listens on `127.0.0.1:8001`.
2. In the dashboard, **Connections**: create "Grok Bot" and copy the token (shown once).
3. Install Cloudflare's connector: `winget install --id Cloudflare.cloudflared`.
4. Start a quick tunnel to the gateway only: `cloudflared tunnel --url http://localhost:8001`. It prints an `https://<random>.trycloudflare.com` address. Quick tunnels are for testing: no uptime guarantee, and a new address each time; a named Cloudflare Tunnel (free account) gives a stable address later.
5. In Grok Bot's chat, ask it to add a custom MCP server: URL `https://<random>.trycloudflare.com/mcp`, with the header `Authorization: Bearer <token>`.
6. In a room, start **Review & improve** with Grok Bot as the worker; Grok Bot calls `get_tasks` and `submit_task`.

Sources: [Cloudflare Quick Tunnels](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/), [How to add MCP servers to Grok Bot (Composio)](https://composio.dev/blog/how-to-add-mcp-servers-to-grok-bot).
