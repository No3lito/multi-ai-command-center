# Multi-AI Command Center: Phase 1 Technical Discovery

Nov 2, 2026 · Noel Rodriguez

> **Revision 1 (Nov 2, 2026), pending owner approval.** Updated after an independent architecture review by ChatGPT, tracked in [issue #1](https://github.com/No3lito/multi-ai-command-center/issues/1). Changes: a minimal authenticated MCP gateway moves into Phase 2; the orchestration engine sits behind a replaceable interface with LangGraph and Microsoft Agent Framework evaluated in Phase 3; security is specified in detail for approvals, duplicate tool execution, budgets, remote access and emergency stop; many agents, concurrent conversations, reconnection and provider capabilities are supported from Phase 2. See the [revision log](#revision-log).

## Executive summary

**Recommendation: Option C, build our own modular platform, reusing MIT-licensed patterns and libraries where they fit.** No inspected project covers more than about a third of the requirements, and every fork candidate carries a trust model or runtime that conflicts with yours.

What that means in practice:

- **We own** the parts that make this product yours: the message protocol, agent registry, permissions and approvals, audit log, budgets, chatroom UI and data model.
- **We borrow** proven designs: AgentPeerChat's identity, inbox and delivery-acknowledgment model; Microsoft Agent Framework's orchestration patterns (sequential, concurrent, group chat, handoff, Magentic manager); the A2A Agent Card for agent discovery; MCP for tools and for external AI clients.
- **We use official SDKs** for Anthropic, OpenAI, Google Gemini, xAI and Ollama behind our own adapter interface, so no framework sits between us and a provider.
- **We simplify the stack**: PostgreSQL with pgvector does storage, vector search, the job queue and real-time fan-out (LISTEN/NOTIFY). Redis is deferred until measured load needs it.
- **We prove cross-AI early** (Revision 1): a minimal authenticated MCP gateway ships in Phase 2, so an external AI client works in a room alongside API-driven agents from the first milestone.
- **We keep the engine swappable** (Revision 1): orchestration runs behind an `OrchestrationEngine` interface, and engines never touch providers, tools or the database directly, so budgets, approvals and audit apply whichever engine wins.

The hardest requirement is cross-AI participation by consumer clients. ChatGPT, Claude web and the Grok API all reach MCP servers **from their vendors' clouds**, so a laptop service is invisible to them. The design answers this with an authenticated MCP gateway exposed through a tunnel, and treats local coding agents (Claude Code, Codex CLI, Gemini CLI) as first-class participants over local MCP.

**Verified vs recommended.** Sections 1 and 6 report what was inspected in code and official docs. Sections 2 to 9 are architectural recommendations. Where a source could not be reached, that is stated.

**Your approval is needed** on the decisions listed in the final section before Phase 2 starts.

## 1. Repository research findings (verified)

All seven repositories exist and their code is MIT-licensed, so patterns and code can be reused with attribution. Each was cloned on Nov 2, 2026 and inspected at the file level, not just the README.

| Project | License | Activity (Nov 2026) | What it actually is | Fit for us |
| --- | --- | --- | --- | --- |
| [AgentPeerChat](https://github.com/AgenticsWorks/AgentPeerChat) | MIT | Active; v0.1.28, last commit Oct 28 | Messaging service only: identities, direct and group threads, durable inbox with ACKs. \~1,600 lines of TypeScript. No model calls, no orchestration | Pattern source for messaging and identity |
| [Microsoft Agent Framework](https://github.com/microsoft/agent-framework) | MIT | Very active; Python core 1.24.0, "Production/Stable" | Agent and workflow library (Python, .NET, Go): provider clients, orchestrations, checkpointing, A2A and MCP hosting | Best orchestration reference; optional library |
| [LangGraph](https://github.com/langchain-ai/langgraph) | MIT | Very active; 1.2.19 | Graph-based stateful workflow engine with Postgres checkpointer and human `interrupt()` | Strong alternative orchestration engine |
| [CrewAI](https://github.com/crewAIInc/crewAI) | MIT | Very active | Role-based crews and event-driven Flows; built-in A2A, MCP, memory | Good role-template ideas; opinionated runtime |
| [AutoGen](https://github.com/microsoft/autogen) | MIT code, CC-BY docs | **Archived**; README advises against production use | Research multi-agent framework, superseded by Agent Framework | Reference only. Do not depend on it |
| [OpenHands](https://github.com/OpenHands/OpenHands) | MIT | Very active | Repo is now "Agent Canvas": a self-hosted control center that runs OpenHands, Claude Code, Codex, Gemini and other ACP agents across backends | Integrate as an external coding participant; UI reference |
| [OpenClaw](https://github.com/openclaw/openclaw) | MIT | Very active | Large personal and team assistant gateway: 200+ extensions (providers, chat channels, A2A, MCP relay, memory) | Too broad to fork; trust model mismatch |

### AgentPeerChat (inspected in depth)

- **Architecture:** a Cloudflare Worker (`src/cloudflare.ts`) with D1 (SQLite) storage and one Durable Object (`MailboxHub`) per agent for push notifications. A Node.js + SQLite server (`server/app.mjs`) provides the same API off Cloudflare, so it does run locally.
- **Identity:** `principals` of kind owner, human or agent; exactly one owner per instance (enforced by a unique partial index). Agents join through hashed, expiring, single-use invites.
- **Auth:** bearer access keys and browser sessions, stored only as hashes, with parent-token revocation cascading to children. Owner-revocable delegation flags (`can_invite_agents`, `can_help_owner_login`).
- **Messaging:** `threads`, `thread_members`, `messages` (types text, json, url, artifact; replies and mentions), and a `deliveries` table that records a per-recipient `acked_at`. Every send carries an idempotency key, unique per sender, so retries never duplicate.
- **Real-time:** WebSocket with a 60-second, single-use ticket passed as a subprotocol (`apc-v1`); tickets can only open a notification stream, never call the REST API. Without Durable Objects it falls back to polling.
- **Agent side:** a CLI plus a SKILL.md, so any agent host that can run Node commands (Claude Code, Codex, OpenClaw) can join. No MCP server is included.
- **Gaps for us:** no orchestration, budgets, tools, sandboxing, approvals, model calls or vector memory; pagination is capped at 100. It solves about 15% of the requirements.

### Microsoft Agent Framework

- 44 Python packages, including clients for `anthropic`, `openai`, `gemini`, `ollama`, `bedrock`, `mistral`, plus `a2a`, `hosting-mcp`, `orchestrations`, `postgres`, `redis`, and `devui`.
- `orchestrations` implements sequential, concurrent, group chat, handoff and Magentic (manager-led) patterns, with an explicit request-info step for human input. The core workflow runner supports checkpointing.
- Caveat: the core is 1.x stable, but the Anthropic, Gemini, Ollama and A2A packages are still beta (`1.0.0b261030`) and MCP hosting is alpha. Depending on them for provider calls would tie us to their release cadence.

### LangGraph

- Libraries for the core graph engine, `checkpoint-postgres` (3.2.0), `checkpoint-sqlite`, a checkpoint conformance suite, prebuilt agents, and Python and JS SDKs.
- `interrupt()` pauses a graph for human approval and resumes from the checkpoint, which maps directly onto our approval gates. It is Python-native and fits a FastAPI backend.

### CrewAI

- Monorepo with `crewai`, `crewai-core`, `crewai-tools`, `crewai-files` and a CLI. Modules for `a2a`, `mcp`, `memory`, `flow`, `hooks` and `security`.
- A `plus_api` module talks to CrewAI's hosted service; usable locally, but it is a full opinionated runtime, not a component.

### OpenHands (Agent Canvas) and OpenClaw

- **Agent Canvas** runs coding agents through ACP (Agent Client Protocol) behind an agent server on port 18000 with an API-key-gated public mode. Valuable as a participant we connect to, and as UI reference for supervising coding agents.
- **OpenClaw's** security policy treats actions by authorized users as trusted host actions and does not count prompt injection as a vulnerability unless a sandbox or policy boundary is bypassed. That is reasonable for a personal assistant but is the opposite of the least-privilege, approval-gated model you specified.

## 2. Fork, combine or build

Option C wins on ownership, security and maintainability, at a cost of roughly 5 extra weeks over a fork to reach the first demo, which (since Revision 1) also includes the MCP gateway and concurrency work. Effort estimates assume one developer working with AI coding agents.

| Criterion | A: Fork (best candidate: OpenClaw or Agent Canvas) | B: Combine (AgentPeerChat + LangGraph + CrewAI) | C: Build, borrowing patterns (recommended) |
| --- | --- | --- | --- |
| Ownership | Low. Upstream drives architecture; large inherited code you did not write | Medium. Three upstreams with different data models | High. Every core data model and protocol is yours |
| Extensibility | High inside the host's plugin model, awkward outside it | Medium. Glue code between runtimes grows fast | High. Adapters, tools and agents are registry entries |
| Security | Inherits a trust model you would have to rework (OpenClaw trusts authorized users at host level) | Weakest. Three permission models, none covers approvals and budgets end to end | Strongest. Least privilege and approvals designed in from day one |
| Complexity | Very high to learn; OpenClaw alone has 200+ extensions | High. TypeScript Cloudflare service plus two Python frameworks | Medium. One Python backend, one Next.js app, one database |
| Performance | Good, but sized for someone else's use case | Overhead from cross-service hops | Good. Postgres-centric, few moving parts |
| Maintainability | Constant rebasing against very active upstreams (50+ commits in weeks) | Three release cadences to track | You control upgrades; libraries stay behind interfaces |
| Effort to first demo | 2 to 3 weeks | 4 to 6 weeks | 7 to 8 weeks (includes MCP gateway) |
| Effort to Phase 6 | 5 to 7 months, mostly rework | 6 to 8 months | 5 to 7 months |

**Why not fork AgentPeerChat specifically:** it is small and clean, but it is TypeScript on Cloudflare, messaging only, and has a single-owner model. We would rewrite most of it to add orchestration, budgets and Postgres. Reusing its design is cheaper than reusing its code.

**Kept open, by design:** the orchestration engine is replaceable. Phase 2 defines the `OrchestrationEngine` interface and ships a built-in engine; Phase 3 runs a time-boxed evaluation of LangGraph and Microsoft Agent Framework behind the same interface; the Phase 4 gate picks one using the criteria in section 3. That choice does not affect the protocol, data model, security controls or UI.

## 3. Proposed system architecture

A single Python backend with clear internal modules sits between every participant and every model, so policy, budgets and audit apply identically to a built-in agent, ChatGPT or you.

![System architecture](phase-1-architecture.png)

Requests flow down: clients reach the API or the MCP gateway, the core checks policy and routes work, workers call models or run tools in a sandbox, and PostgreSQL records everything.

### Layers and responsibilities

| Layer | Responsibility | Technology |
| --- | --- | --- |
| Dashboard | Three-pane chat UI, agent directory, task board, approvals, cost view, emergency stop | Next.js, React, TypeScript (strict), Tailwind |
| API | REST, WebSocket, webhooks for the dashboard and custom clients | FastAPI |
| MCP gateway | Separate listener for external AI clients; bearer tokens in Phase 2, OAuth 2.1 in Phase 5 | Official MCP Python SDK, Streamable HTTP |
| Messaging | CCMP envelopes, rooms, DMs, delivery ACKs, replay, turn-taking | Postgres tables + LISTEN/NOTIFY |
| Orchestrator | Plans, task graph, assignment, turn and budget limits, completion checks | `OrchestrationEngine` interface; built-in engine first, LangGraph and Agent Framework evaluated in Phase 3 |
| Policy and approvals | Permission checks, approval queue, audit chain | Own module; rules as data |
| Registry | Agent profiles, tools, MCP servers, skills, provider configs | Postgres, versioned rows |
| Memory | Scoped storage, embeddings, summaries, context assembly | pgvector, local embeddings via Ollama |
| Workers | Model calls, tool runs, workflow steps from the job queue | Python async workers, SKIP LOCKED queue |
| Execution | Per-task containers and git worktrees | Docker (rootless where possible) |

### Replaceable orchestration engine (Revision 1)

The orchestrator is an interface, not a framework choice. Every engine, built-in or adopted, plugs in behind it and talks to the rest of the platform only through narrow ports.

```python
class OrchestrationEngine(Protocol):
    name: str
    async def start_run(self, spec: RunSpec, ports: EnginePorts) -> RunHandle: ...
    async def resume(self, run_id: RunId, ports: EnginePorts) -> RunHandle: ...
    async def signal(self, run_id: RunId, signal: RunSignal) -> None: ...   # approval decided, message arrived, timer
    async def cancel(self, run_id: RunId, reason: str) -> None: ...
    async def state(self, run_id: RunId) -> RunState: ...

class EnginePorts(Protocol):
    models: ModelPort        # wraps provider adapters + budget reservation
    tools: ToolPort          # wraps policy engine, approvals, idempotent execution
    messages: MessagePort    # posts and reads CCMP messages
    store: StatePort         # checkpoints run state in Postgres
    clock: ClockPort         # deadlines and timers
```

Rules every engine must follow:

- **No direct side effects.** An engine never imports a provider SDK, runs a tool, or writes to the database itself. Everything goes through `EnginePorts`, so budgets, approvals, idempotency, audit and the emergency stop apply identically to every engine.
- **Checkpoint at every step boundary** through `StatePort`, so a restart resumes the run and a swap of engine never strands state in a framework-specific store.
- **Pass the contract suite.** The same tests run against every engine: approval interrupt and resume, cancellation mid-step, crash and resume, parallel branches, turn and budget limits, emergency stop within 5 seconds.

Evaluation plan:

| Step | When | Output |
| --- | --- | --- |
| Interface, ports and contract tests; built-in engine passes them | Phase 2 | Working MVP on the built-in engine |
| Spike: the Phase 2 demo flow on LangGraph, then on Microsoft Agent Framework, behind the interface (about 3 days each) | Phase 3 | Two adapters plus test results |
| Written comparison against the criteria below | End of Phase 3 | `docs/decisions/` record |
| Decision: keep built-in, adopt one, or support both | Phase 4 gate | Owner approval |

Criteria: contract suite pass rate; durable checkpointing on our Postgres; human-in-the-loop interrupt and resume; cancellation and timeout behavior; parallel and hierarchical workflows; how cleanly it runs with our ports and no provider clients of its own; license (both MIT); release maturity of the packages we would depend on (Agent Framework's core is 1.x stable while several integrations are beta); dependency weight; and debuggability.

### Evaluation of your proposed stack

Kept as proposed: Next.js, Tailwind, FastAPI, PostgreSQL, pgvector, WebSockets, Ollama, Docker, Docker Compose, Git, Pytest, Vitest, Playwright. Changed: Redis deferred (Postgres covers queue and fan-out for one operator), and the orchestrator starts as a built-in engine behind a replaceable interface, with LangGraph and Microsoft Agent Framework evaluated against it in Phase 3. Added: `uv` for Python dependency pinning and Alembic for migrations.

## 4. Database and messaging design

One PostgreSQL 16 database with pgvector holds everything, and every agent-to-agent exchange is a row in `messages` written through one protocol, the **Command Center Message Protocol (CCMP) v1**.

### CCMP v1 message envelope

Every participant, whether a built-in agent, an external AI client or a human, sends and receives the same envelope. Providers never see it; adapters translate it into each provider's chat format.

```json
{
  "id": "msg_01J...",
  "protocol": "ccmp/1",
  "room_id": "room_...",
  "thread_id": "thr_...",
  "sender": {"principal_id": "agt_...", "kind": "agent"},
  "recipients": ["agt_..."],
  "kind": "chat | task.assign | task.result | task.status | tool.request | tool.result | approval.request | approval.decision | artifact | error | control",
  "reply_to": "msg_...",
  "mentions": ["agt_..."],
  "body": {"text": "...", "data": {}},
  "task_id": "tsk_...",
  "correlation_id": "run_...",
  "idempotency_key": "client-generated",
  "usage": {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0},
  "created_at": "2026-11-02T16:41:00Z"
}
```

Adopted from AgentPeerChat: sender-scoped idempotency keys, per-recipient delivery rows with ACK timestamps, monotonic sequence numbers for cursor paging, and single-use short-lived WebSocket tickets.

### Core tables

| Table | Purpose | Key columns |
| --- | --- | --- |
| `principals` | Humans, agents and external clients | kind, display\_name, status, suspended\_at |
| `credentials` | Hashed API keys, MCP client tokens and sessions; never plaintext | principal\_id, hash, scopes (rooms, tools), expires\_at, revoked\_at, last\_used\_at |
| `agent_profiles` | Versioned agent configuration | role, provider, model, system\_prompt, tool\_ids, memory\_policy, budget, approval\_policy |
| `providers` | Provider connections and discovered capabilities | adapter, base\_url, capabilities JSON, secret\_ref |
| `projects`, `rooms`, `room_members` | Isolation boundary and chatrooms; any number of members | project\_id on every downstream row; room turn\_policy |
| `messages`, `deliveries` | CCMP log and per-recipient ACK | seq, idempotency\_key, acked\_at |
| `tasks`, `task_edges` | Work items and dependency graph | status, owner, parent\_id, depth, acceptance\_criteria |
| `workflow_runs`, `run_steps` | Engine checkpoints, resumable after restart | engine, state JSON, turn\_count, spend\_usd, deadline, status |
| `agent_turns` | One active turn per agent per run | run\_id, agent\_id, status, lease\_expires\_at (unique on run\_id, agent\_id where active) |
| `approvals` | Human gates bound to an exact action | action JSON, action\_hash, risk\_level, requested\_by, expires\_at, decided\_by, decided\_at, consumed\_at |
| `tool_calls` | Every tool invocation and its execution state | idempotency\_key (unique), tool\_id, args hash, side\_effect class, state, attempt, lease\_expires\_at, result, approval\_id |
| `budget_reservations` | Money held before a model or tool call | scope (run, agent, project, month), reserved\_usd, actual\_usd, status |
| `usage_ledger` | Tokens and dollars per call | agent, provider, model, tokens, cost\_usd, reservation\_id |
| `system_controls` | Global switches | halted, halted\_by, halted\_at, external\_access\_enabled, version |
| `memories` | Scoped memory with embeddings | scope (project, agent, room), content, `embedding vector(N)`, source |
| `artifacts` | Files, code, reports | storage path, sha256, produced\_by\_task |
| `audit_events` | Append-only security log | actor, action, target, prev\_hash (hash chain) |

### Real-time and queueing without Redis

- **Fan-out:** after each insert into `messages`, a `NOTIFY` on the room channel wakes the API process, which pushes to subscribed WebSockets. Clients reconnect with their last `seq` and replay what they missed, so a dropped connection loses nothing.
- **Jobs:** model calls, tool runs and workflow steps are rows claimed with `SELECT ... FOR UPDATE SKIP LOCKED` by worker processes. Restart-safe and inspectable with plain SQL.
- **When to add Redis:** if sustained traffic exceeds a few hundred messages per second or workers span machines. The queue sits behind an interface so the swap is local.

### Scale and concurrency from Phase 2 (Revision 1)

Nothing in the data model, protocol or scheduler assumes two agents or one conversation. Phase 2 proves this with a load test, not just the single demo.

- **Many agents:** rooms hold any number of members; agent counts, rooms and runs are limited only by configurable quotas.
- **Turn-taking policy per room**, so N agents do not all answer every message (which grows cost and noise with N squared):
    - *Coordinator-directed* (default): only agents the coordinator assigns take a turn.
    - *Mention-based:* only agents named in `mentions` respond.
    - *Round-robin:* a bounded rotation for open debate.
- **Concurrency limits** at four levels, all configurable: global workers, per provider (to respect rate limits), per run, and per agent. One active turn per agent per run, enforced by a unique constraint on `agent_turns`.
- **Fair scheduling:** the job queue orders by run priority and wait time, so one busy room cannot starve the others.
- **Isolation:** each run's state is locked per row; runs share nothing in memory, so a failure in one run never affects another.
- **Reconnection:**
    - Dashboard WebSockets send heartbeats every 15 seconds; clients reconnect with exponential backoff and a `last_seq`, and the server replays everything after it from Postgres.
    - MCP clients read with a cursor (`read_messages(after_seq)`), so a client that disconnects for an hour resumes exactly where it stopped.
    - Assignments to external clients carry deadlines; when one lapses, the coordinator reassigns or asks the human. A disconnected client never blocks a run.
    - Worker crashes are recovered by lease expiry: an unfinished job becomes claimable again, subject to the tool-execution rules in section 7.

### Memory and context

- Memories are always filtered by `project_id` and the agent's allowed scopes before vector search, so similarity can never cross a project boundary.
- Context assembly per turn: system prompt, task brief, the last N room messages, a rolling summary of older messages, then top-k memories, trimmed to the target model's context budget.
- Deletion removes rows and embeddings together and writes an audit event. Embeddings can come from a local Ollama model, keeping memory fully local.

## 5. AI provider integration strategy

Each provider gets a thin adapter built on its official SDK, implementing one Python interface; capabilities are declared per model and verified by a conformance test suite, never assumed.

### Adapter interface

```python
class ProviderAdapter(Protocol):
    id: str                                   # "anthropic", "openai", "xai", "gemini", "ollama"
    async def list_models(self) -> list[ModelInfo]: ...
    def capabilities(self, model: str) -> Capabilities: ...
    async def generate(self, req: ChatRequest) -> ChatResponse: ...
    def stream(self, req: ChatRequest) -> AsyncIterator[ChatEvent]: ...
    def estimate_cost(self, usage: Usage, model: str) -> Decimal: ...
    async def health(self) -> ProviderHealth: ...
```

`Capabilities` covers streaming, tool calling, parallel tool calls, structured output (JSON schema), vision, context window, max output tokens, and server-side MCP. `ChatRequest` is provider-neutral (messages, tools as JSON Schema, response schema, limits); each adapter maps it to the native format and maps errors to a shared set: `rate_limited`, `auth_failed`, `context_overflow`, `content_refused`, `unavailable`, `bad_request`.

### Planned adapters

| Adapter | SDK | Notes |
| --- | --- | --- |
| Anthropic Claude | `anthropic` (Python) | Messages API; native tool use and streaming |
| OpenAI | `openai` | Responses API preferred; Chat Completions kept for compatibility |
| xAI Grok | `xai-sdk` or `openai` pointed at xAI's endpoint | xAI documents an OpenAI-compatible Responses API ([xAI docs](https://docs.x.ai/developers/tools/remote-mcp)); verify feature parity per model in conformance tests |
| Google Gemini | `google-genai` | Gemini API with API key; Vertex AI as a later option for enterprise accounts |
| Ollama (local) | `ollama` or its OpenAI-compatible endpoint | Tool support varies by model, so capability flags come from a live probe |
| Others | OpenAI-compatible adapter | Covers OpenRouter, LM Studio, vLLM and similar with one adapter plus config |

### Behaviors that matter

- **Tools run on our side.** Models only propose tool calls; the orchestrator checks permissions and executes them in the sandbox. Provider-side tool execution (such as server-side remote MCP) is off by default because it bypasses our approval gates.
- **Capability fallback** is configured per agent: if a model lacks structured output, the adapter asks for JSON and validates it with a retry; if it lacks tool calling, the agent is restricted to chat roles. Fallback to a different provider happens only if the agent's profile allows it, and is logged.
- **Same or different models at once:** agents reference a model by `provider:model`, and adapters are stateless, so ten agents can share one model or use five different ones.
- **Cost accounting** reads token usage from each response and multiplies by a price table stored in the database (editable, versioned), because list prices change. Unknown models are flagged rather than costed at zero.
- **Secrets** live in a local secrets store (Docker secrets or an encrypted file in the MVP, a vault later), referenced by `secret_ref`; keys never enter the database, logs or model context.
- **API, not consumer apps.** Built-in agents use paid API keys. ChatGPT, Claude.ai and Grok consumer apps are only ever external clients through the gateway described next.

### Provider-specific capabilities from Phase 2 (Revision 1)

- **Capability registry in Phase 2**, even though only two adapters ship then. Each model's `Capabilities` record is stored in `providers`, refreshed from the adapter, and confirmed by the conformance suite (live probes for tool calling, structured output and streaming).
- **Assignment validation:** an agent profile declares what its role needs (for example tool calling and structured output for a Developer). Saving a profile, or assigning a task, fails with a clear error if the chosen model lacks a required capability, instead of failing mid-run.
- **Typed extensions, not a lowest common denominator.** `ChatRequest` and `ChatResponse` carry an `extensions` field keyed by provider (for example extended thinking settings, reasoning effort, or provider-hosted search). The core never reads it; only the matching adapter does, and unknown keys are rejected so typos do not pass silently.
- **Per-provider limits** (requests and tokens per minute) live alongside capabilities and feed the scheduler's per-provider concurrency limit.

## 6. Cross-AI interoperability strategy

MCP is the one door every major AI client can use today, so the platform exposes a single **Command Center MCP server** with the same tools to all of them; what differs is only where the client runs and therefore how it reaches the server.

### How each client can reach the platform (verified Nov 2026)

| Client | Officially supported mechanism | Runs from | Reaches a laptop directly? |
| --- | --- | --- | --- |
| ChatGPT (web) | Developer mode apps backed by a remote MCP server; SSE or streaming HTTP; OAuth or no auth; write tools need confirmation by default. Pro, Plus, Business, Enterprise, Education ([OpenAI](https://developers.openai.com/api/docs/guides/developer-mode)) | OpenAI cloud | No: needs a public HTTPS URL |
| Claude.ai / Claude apps | Custom connectors from an HTTPS URL with OAuth or no sign-in; private networks via MCP tunnels; local servers via desktop extensions ([Claude docs](https://www.claude.com/docs/connectors/custom/remote-mcp)) | Anthropic cloud (URL) or your desktop (extension) | Only through the desktop app or a tunnel |
| Grok via xAI API | Remote MCP tools in the Responses API and xAI SDK; streaming HTTP or SSE; Authorization header; xAI runs the calls server-side; `require_approval` not supported ([xAI](https://docs.x.ai/developers/tools/remote-mcp)) | xAI cloud | No: needs a public HTTPS URL |
| Gemini CLI | MCP over stdio, SSE or streamable HTTP; OAuth, headers, Google credentials; per-tool confirmation unless `trust` is set ([Gemini CLI docs](https://github.com/google-gemini/gemini-cli/blob/main/docs/tools/mcp-server.md)) | Your machine | Yes |
| Claude Code, Codex CLI, OpenCode | Local MCP servers (stdio or HTTP) | Your machine | Yes |
| Agent Canvas / OpenHands agents | ACP agent server with API key (inspected in repo) | Your machine or a server | Yes |
| Other agent platforms | A2A v1.0: Agent Card at `/.well-known/agent-card.json`, Linux Foundation governed ([A2A](https://a2a-protocol.org/v1.0.0/topics/agent-discovery/)) | Anywhere | Depends on host |

Grok's consumer app and Gemini's consumer app were not confirmed to support custom MCP servers; treat them as unsupported until verified.

### Minimal gateway in Phase 2 (Revision 1)

Cross-AI communication is demonstrated in the first milestone rather than in Phase 5. The Phase 2 gateway is deliberately small:

| Aspect | Phase 2 | Phase 5 adds |
| --- | --- | --- |
| Transport | MCP Streamable HTTP on its own listener, bound to `127.0.0.1` | stdio launcher for CLIs; A2A Agent Card |
| Auth | Per-client bearer tokens: random, shown once, stored hashed, scoped to rooms and tools, expiring (default 30 days), revocable | OAuth 2.1 with dynamic client registration, required by ChatGPT and Claude.ai connectors |
| Tools | `list_rooms`, `read_messages` (cursor), `post_message`, `get_my_tasks`, `submit_result` | `list_agents`, `claim_task`, `get_artifact`, `request_tool_run` |
| Exposure | Local only. Optional stretch: Grok API through a time-boxed tunnel, with explicit owner approval | Tunnel management in the dashboard |
| Protections | Origin and Host header validation, per-token rate limit, request size limit, audit of every call, write tools annotated as write | Per-client usage dashboards |

The Phase 2 proof: a local MCP client (Claude Code or Gemini CLI) joins the demo room with its own token, reads the conversation, posts a critique, and the API-driven agents respond to it.

### Gateway design

1. **Command Center MCP server** (streamable HTTP, plus stdio for local CLIs) exposes scoped tools: `list_rooms`, `read_messages`, `post_message`, `list_agents`, `get_my_tasks`, `claim_task`, `submit_result`, `get_artifact`, `request_tool_run`. Tools are annotated read-only or write so ChatGPT and others prompt correctly.
2. **External principal per client.** Each client (for example "ChatGPT-Noel") is a principal with its own credential, scopes and room memberships. It sees only what its scopes allow, exactly like a built-in agent.
3. **OAuth 2.1 authorization server** built into the API in Phase 5 (dynamic client registration supported), so ChatGPT and Claude can connect with a sign-in rather than a static key. Grok gets a scoped bearer token from Phase 2, since its remote MCP uses an Authorization header.
4. **Public exposure only through a tunnel** (Cloudflare Tunnel or Tailscale Funnel) that publishes the MCP gateway listener alone, under the remote-access rules in section 7. The dashboard, admin API, database and workers stay on localhost.
5. **Asynchronous by design.** Consumer clients only act when you prompt them, so assignments wait in their inbox until they call `get_my_tasks`. The orchestrator applies deadlines and reassigns if a client does not respond, so nothing stalls when a client disconnects.
6. **REST, WebSocket and webhooks** carry the same CCMP envelope for custom clients and scripts. A2A is added in Phase 5 so A2A-speaking agents (Microsoft Agent Framework, CrewAI, OpenClaw) can join through an Agent Card.

### Two classes of participant

- **Driven agents:** built-in agents whose turns the orchestrator starts with an API call. Fully autonomous within budgets.
- **Self-driven clients:** ChatGPT, Claude.ai, Grok, Gemini CLI, Claude Code and others that connect in and act when their own session runs. They are first-class in the room and task model, but the platform never assumes they will answer on time.

## 7. Security and permissions design

Every action is checked against one policy engine before it runs, deny by default, and anything at Level 4 stops for your approval no matter which agent or client asks.

### Policy model

A request is allowed only if all four scopes allow it: **principal** (agent or client) × **project** × **tool** × **environment** (dev, sandbox, prod). Policies are versioned rows, evaluated in one function so they can be unit tested. Your four levels map to tool risk classes:

| Level | Examples | Default gate |
| --- | --- | --- |
| 1 Research and planning | Read docs, web search, read repo, write plans | Auto-allow within budget |
| 2 Development | Edit files on an agent branch, install allowlisted packages, run tests | Auto-allow inside the sandbox |
| 3 Controlled execution | Run the app in a sandbox, start sub-workflows, call external APIs on the allowlist | Auto-allow with limits; first use per run asks |
| 4 Privileged | Merge to main, deploy, delete data, change credentials, send email, spend over threshold, access sensitive data | Always requires a logged human approval |

### Execution sandbox

- One Docker container per task run, built from a pinned image; non-root user, read-only root filesystem, dropped Linux capabilities, `no-new-privileges`, CPU, memory, PID and time limits.
- Only the task's git worktree is mounted, read-write. Never the Docker socket, home directory or host paths.
- Network off by default; when a task needs it, egress goes through a proxy with a domain allowlist (package registries, GitHub, approved APIs).
- Secrets are injected per call as short-lived environment values only for tools that declare them; they are redacted from logs and never placed in model context.
- Hardening option for later phases: gVisor or Kata runtime for stronger isolation on Linux.

### Prompt-injection containment

- Content from web pages, files, tool output and external clients is tagged as untrusted data in context and can never raise permissions or approve anything.
- Approvals are only accepted from a human session in the dashboard, never from a message in a room, including messages that claim to be from you.
- External AI clients get the narrowest scopes; write tools are annotated so their own UIs ask before acting.

### Human approvals (Revision 1, ships in Phase 2)

An approval authorizes one exact action, once, for a short time. It cannot be replayed, widened or granted by an agent.

- **Bound to the action.** The request stores the canonical action (tool, arguments, target, risk level) and its SHA-256 `action_hash`. At execution time the worker recomputes the hash; any difference, even one argument, voids the approval and a new request is raised.
- **Single-use and expiring.** `consumed_at` is set in the same transaction that starts execution; a consumed or expired approval (default 15 minutes) can never authorize anything again.
- **Human-only decisions.** Only an authenticated dashboard session can decide, with CSRF protection. Agents, external MCP clients, room messages and tool output cannot approve, and the principal that requested an action cannot decide it.
- **Step-up for Level 4.** Privileged actions require re-authentication (password or passkey) within the last 5 minutes.
- **What you see is what runs.** The approval card shows the exact arguments, diff or command, the requesting agent, estimated cost and risk level. Approval ids never appear in model context.
- **Everything logged:** request, decision, decider, step-up result, and the execution outcome, in the hash-chained audit log.

### Preventing duplicate tool execution (Revision 1, ships in Phase 2)

Retries, worker crashes and duplicated model output must never run a side effect twice.

- **Deterministic idempotency key** for every tool call: hash of run id, step id, tool id and canonical arguments. `tool_calls.idempotency_key` is unique, so a second insert returns the existing call and its result instead of executing again.
- **Explicit state machine:** `proposed → awaiting_approval → approved → executing → succeeded | failed | unknown`. Transitions are compare-and-set updates; only one worker can move a call to `executing`.
- **Leases:** a worker holds a lease while executing and renews it; if it dies, the lease expires.
- **Side-effect classes decide recovery:**
    - *Read-only* tools may be retried automatically (at-least-once).
    - *Idempotent writes* (for example, writing a file to an exact path) retry with the same key.
    - *Non-idempotent side effects* (send, merge, deploy, external POST) are at-most-once: after a crash they move to `unknown` and wait for human reconciliation, never an automatic retry. Where an external API accepts an idempotency key, ours is passed through.
- **Results are stored with the call**, so a replayed engine step reads the recorded result rather than calling the tool again.

### Budget enforcement (Revision 1, ships in Phase 2)

- **Reserve before spending.** Before each model call, the worker reserves the worst-case cost (`max_tokens` × output price plus input tokens × input price) against four scopes in one database transaction: run, agent, project and the monthly global cap. If any scope would go negative, the call does not happen and the run pauses with a visible notice.
- **Reconcile after.** Actual usage replaces the reservation; the difference is released. Abandoned reservations expire and are released by a sweeper.
- **No unbounded calls.** `max_tokens` is always set from the agent profile; streaming calls are cut off at the reserved ceiling.
- **Unknown prices are blocked** unless the owner explicitly allows that model, so a new model can never be costed at zero.
- **Thresholds notify** at 50%, 80% and 100% of each budget; raising a budget is a Level 4 action.

### Remote access (Revision 1)

- **Off by default.** Every listener binds to `127.0.0.1`. External access is a single switch in `system_controls`, off at install.
- **Separate surfaces.** The MCP gateway runs on its own listener and router. The dashboard, admin API, WebSocket, database and workers are never reachable through a tunnel, and requests for those paths on the gateway listener return 404.
- **Owner-approved, time-boxed tunnels.** Turning on a tunnel is a Level 4 action with an expiry (default 8 hours); it shuts off automatically.
- **Per-client tokens** with narrow scopes, expiry, rotation and instant revocation; `last_used_at` and source IP are logged on every call.
- **Request hygiene:** Origin and Host validation (DNS-rebinding protection), per-token and per-IP rate limits, request size limits, TLS terminated at the tunnel.
- **Kill switch:** one action suspends every external principal and closes the tunnel; it is also part of the emergency stop.

### Emergency stop (Revision 1, ships in Phase 2)

- **One control** in the dashboard header, also callable from the CLI on the host. It sets `system_controls.halted` and broadcasts a `control` message.
- **Checked everywhere:** before every model call, tool call and engine step, and by every worker heartbeat (every 2 seconds).
- **Active work is stopped, not just new work:** in-flight streaming model calls are aborted, sandbox containers are killed, queued jobs are cancelled, external MCP tokens are suspended, and pending approvals are frozen.
- **State is preserved** for review: runs move to `halted`, not `failed`, with a record of what was interrupted.
- **Target: everything stopped within 5 seconds**, verified by an automated test that halts a run mid-stream and mid-tool.
- **Resume** requires step-up re-authentication and is logged; runs resume individually, not all at once.

### Runaway controls (from the brief, all configurable)

- Per run: max turns, wall-clock deadline, token and dollar budget, retry limit, delegation depth (default 3).
- Cycle detection on the task graph at assignment time; a watchdog that fails runs with no progress for N minutes (deadlock).
- Emergency stop and budget enforcement as specified above.

### Audit

- Append-only `audit_events` with a hash chain, so tampering is detectable. Logged: every model call (metadata and usage), tool call, permission decision, approval and config change.
- Healthcare boundary: no protected health information in development or testing. Any future Path W-ai or ACO data integration requires a separate, BAA-covered deployment with its own project isolation and access review.

## 8. Roadmap, MVP acceptance tests and repository structure

The first live demo (two providers and one external MCP client collaborating on a login screen, with an approval gate) lands at the end of Phase 2, about 7 to 8 weeks after approval; each phase ends at a gate you sign off.

### Phases (estimates assume one developer plus AI coding agents)

1. **Phase 2: Minimum viable chatroom with cross-AI access (7 to 8 weeks; was 5 to 6).** Monorepo, Docker Compose (Postgres, API, gateway, worker, web), CCMP v1 schema, owner sign-in with step-up re-authentication, principals and tokens, rooms with any number of members and turn-taking policies, persistent messages, WebSocket fan-out with resume, Anthropic and OpenAI adapters with the capability registry and conformance tests, `OrchestrationEngine` interface plus built-in engine and contract tests, approvals bound to actions, idempotent tool-call state machine, budget reservations, emergency stop, minimal MCP gateway with bearer tokens. Gate: the acceptance tests below pass against live APIs.
2. **Phase 3: Agent collaboration and engine evaluation (4 weeks; was 3).** Agent profiles and the eight role templates, task model with assignments and handoffs, shared task context, completion criteria checks, xAI, Gemini and Ollama adapters with conformance tests, and the LangGraph and Microsoft Agent Framework spike behind the engine interface.
3. **Phase 4: Controlled autonomy (5 to 6 weeks).** Workflow patterns (sequential, parallel, hierarchical, event-driven), Docker sandbox, git worktree per agent, reviewer and QA loops, full policy engine, audit chain. Gate decision: which orchestration engine to keep, based on the Phase 3 evaluation.
4. **Phase 5: Customization and interoperability (3 weeks; was 4).** Agent and workflow editors, memory management with pgvector, provider switching, cost dashboards, tool and MCP registry, OAuth 2.1 for the gateway (ChatGPT and Claude.ai connectors), tunnel management, A2A Agent Card.
5. **Phase 6: Production hardening (4 weeks).** Multi-user auth and RBAC, security testing, backup and restore, observability (OpenTelemetry), performance tests, deployment docs.

### MVP acceptance tests (Phase 2 gate, Revision 1)

**Core demo**

- [ ] `docker compose up` on a clean machine brings up all services; `make demo` seeds one human, one coordinator, two API agents and one external MCP client token.
- [ ] Agent A runs on Anthropic and Agent B on OpenAI; both make **real API calls**, and the usage ledger shows non-zero tokens and cost for each provider.
- [ ] Human posts "Create a basic login interface"; the coordinator assigns planning to A, critique to B, and revision back to A, visible as task status changes in the right sidebar.
- [ ] B's critique references A's plan by `reply_to`; A's revision references B's critique.
- [ ] The coordinator posts a summary and an `approval.request`; the run stays paused until the human approves or rejects in the dashboard, and the decision is in `audit_events`.

**Cross-AI through the MCP gateway**

- [ ] A local MCP client (Claude Code or Gemini CLI) connects to the gateway with its token, lists only the rooms it is scoped to, reads the demo conversation, and posts a message that the coordinator routes to an API agent, which replies.
- [ ] Requests with no token, an expired token, a revoked token or a token scoped to another room are rejected and audited.
- [ ] Requests with a bad Origin or Host header are rejected; the gateway listener returns 404 for dashboard and admin paths.
- [ ] Optional stretch, only with explicit owner approval: Grok API joins through a time-boxed tunnel using a scoped bearer token.

**Many agents, concurrency and reconnection**

- [ ] Load test: 3 rooms run concurrently with 4 or more agents each (mixing both providers); every message is delivered once and in order per room, and no agent has two active turns in one run.
- [ ] Coordinator-directed and mention-based turn policies are each shown in a room with 4 or more agents: only selected agents respond.
- [ ] Per-provider concurrency limits hold under load (verified from logs), and one room's load does not starve another.
- [ ] Killing a browser's network for 60 seconds and restoring it replays every missed message without a refresh; a second tab receives new messages in under 1 second.
- [ ] Disconnecting the MCP client mid-run does not block the run; when it reconnects, `read_messages(after_seq)` returns exactly what it missed.
- [ ] Restarting all containers mid-conversation loses no messages, and runs resume from their last checkpoint.

**Provider capabilities**

- [ ] The capability registry lists verified capabilities for each configured model, and the conformance suite passes for both adapters.
- [ ] Assigning a role that needs tool calling to a model without it is rejected with a clear message before the run starts.
- [ ] A provider-specific option passed through `extensions` reaches only its own adapter; an unknown extension key is rejected.

**Security controls**

- [ ] An approval cannot be reused: a second execution attempt with a consumed approval fails, an expired approval fails, and changing one argument after approval forces a new request.
- [ ] An agent or MCP client attempting to approve its own request is refused and audited; a Level 4 approval without recent step-up re-authentication is refused.
- [ ] Duplicate execution test: the same tool call submitted twice, and a worker killed mid-execution, never run a non-idempotent side effect twice; the crashed call shows as `unknown` awaiting reconciliation.
- [ ] Budget test: two concurrent calls that together exceed a run's $0.50 budget cannot both start; the run pauses with a visible notice, and actual spend never exceeds the cap.
- [ ] Unknown model pricing blocks the call unless explicitly allowed.
- [ ] Emergency stop during a streaming model call and during a running tool stops all activity within 5 seconds, suspends MCP tokens, and leaves runs in `halted`; resuming requires step-up re-authentication.
- [ ] A run with a 12-turn limit stops cleanly at the limit; revoking one provider key mid-run shows an error notification without crashing the room.

**Engine abstraction and automated tests**

- [ ] The built-in engine passes the engine contract suite (approval interrupt and resume, cancellation, crash recovery, turn and budget limits, emergency stop), and nothing outside `orchestrator/` imports it directly.
- [ ] Automated: Pytest (adapters, protocol, engine contract, policy, approvals, idempotency, budgets, gateway), Vitest (UI state), Playwright end-to-end for the full demo; live-API and load tests are tagged and run on demand, with results attached to the Phase 2 report.

### Repository structure

Adjusted from your proposal: one Python package with separate processes instead of five services at first (fewer moving parts, same boundaries), and the protocol defined once as JSON Schema that generates both Pydantic and TypeScript types.

```
multi-ai-command-center/
├── apps/
│   └── web/                     # Next.js + TypeScript (strict) + Tailwind
├── backend/                     # Python 3.12, FastAPI, uv
│   └── command_center/
│       ├── api/                 # REST, WebSocket, dashboard auth
│       ├── gateway/             # MCP server on its own listener (tokens, later OAuth)
│       ├── orchestrator/        # OrchestrationEngine interface, ports, engines, contract tests
│       ├── workers/             # job runner (model calls, tool runs)
│       ├── execution/           # sandbox manager, git worktrees
│       ├── providers/           # adapters + conformance tests
│       ├── policy/              # permissions, approvals, budgets
│       ├── memory/              # context assembly, pgvector
│       └── db/                  # SQLAlchemy models, Alembic migrations
├── packages/
│   ├── protocol/                # CCMP JSON Schema -> Pydantic + TS types
│   └── ui-components/
├── infrastructure/
│   ├── docker/                  # Dockerfiles, sandbox base image
│   └── compose/
├── tests/e2e/                   # Playwright
├── docs/                        # architecture, ADRs, runbooks
├── scripts/
├── AGENTS.md                    # shared rules for every coding agent
├── CLAUDE.md                    # imports AGENTS.md + Claude-specific workflow
├── .env.example
├── docker-compose.yml
└── README.md
```

`CLAUDE.md` imports `AGENTS.md` rather than duplicating it, so Codex, Gemini CLI and Claude Code read one set of rules. Each coding agent works in its own worktree and branch; merges to `main` are Level 4.

## 9. Hardware, operations and decisions needed

With cloud model APIs, the whole platform runs on an ordinary development machine; only local models raise the hardware bar.

### Hardware (estimates)

| Setup | CPU / RAM | Storage | GPU or unified memory |
| --- | --- | --- | --- |
| Cloud models only (MVP) | 4 cores, 16 GB | 50 GB SSD | None |
| Plus small local models (7B to 8B, quantized) | 8 cores, 32 GB | 100 GB | 8 to 12 GB VRAM, or Apple Silicon with 16 GB+ |
| Plus mid-size local models (30B class) | 8+ cores, 64 GB | 200 GB | 24 GB VRAM, or Apple Silicon with 48 GB+ |
| Many parallel sandboxed agents | 12+ cores, 64 GB | 250 GB | As above |

Docker Desktop (macOS, Windows) or Docker Engine (Linux) is required. The local stack itself (Postgres, API, worker, web) idles under 2 GB of RAM.

### Operating costs

- **Software:** $0. Every component is open source; tunnel free tiers cover single-user exposure.
- **Model APIs:** the only real cost, driven by how much agents talk. Per-run and monthly budgets are enforced in code from Phase 2, and the cost dashboard shows spend per agent and provider. Set a starting monthly cap (decision 4).
- **Time:** about 23 to 25 weeks of build to Phase 6 at the estimates above (was 21 to 23 before Revision 1).

### Decisions requiring your input

1. **Approach:** approve Option C (build, borrowing patterns), or choose A or B.
2. **First two providers for the demo:** recommended Anthropic and OpenAI; xAI and Gemini follow in Phase 3. Confirm you have API keys (not just consumer subscriptions) for each.
3. **Stack change:** approve dropping Redis from the MVP in favor of Postgres-based queueing and LISTEN/NOTIFY.
4. **Budgets:** default per-run cap (suggested $1.00) and monthly cap for development (you set).
5. **Your workstation:** OS, RAM, and GPU or Apple Silicon model, to size local-model support and the sandbox runtime.
6. **External exposure:** which local MCP client to use for the Phase 2 proof (Claude Code or Gemini CLI); whether to attempt the optional Grok-through-tunnel stretch in Phase 2; and Cloudflare Tunnel or Tailscale.
7. **Orchestration engine:** approve the plan in section 3 (built-in engine behind a replaceable interface, LangGraph and Agent Framework spike in Phase 3, decision at the Phase 4 gate).
8. **Users:** single operator for now, or plan multi-user RBAC earlier than Phase 6.
9. **Repository:** resolved. [No3lito/multi-ai-command-center](https://github.com/No3lito/multi-ai-command-center), public.
10. **Scope boundary:** confirm the platform stays separate from Pathways and Path W-ai data until a compliant deployment is designed.
11. **Revision 1 timeline:** accept Phase 2 growing to 7 to 8 weeks in exchange for cross-AI access, concurrency and the security controls landing in the first milestone.

## Revision log

| Revision | Date | Source | Changes |
| --- | --- | --- | --- |
| 1 | Nov 2, 2026 | Independent architecture review by ChatGPT; owner request in [issue #1](https://github.com/No3lito/multi-ai-command-center/issues/1) | Minimal authenticated MCP gateway moved into Phase 2 (section 6); replaceable `OrchestrationEngine` interface with a LangGraph and Agent Framework evaluation plan (section 3); detailed controls for approvals, duplicate tool execution, budgets, remote access and emergency stop (section 7); many agents, turn-taking, concurrency limits and reconnection (section 4); capability registry, assignment validation and typed extensions (section 5); new tables `agent_turns`, `budget_reservations`, `system_controls` and expanded `approvals` and `tool_calls` (section 4); rewritten Phase 2 acceptance tests and revised timeline (sections 2, 8, 9) |
| 0 | Nov 2, 2026 | Claude, Phase 1 discovery | Initial report |

The architecture diagram in section 3 is unchanged by Revision 1: it already shows the MCP gateway as its own component and the policy engine at the center.

## Sources

Repositories cloned and inspected Nov 2, 2026: [AgentPeerChat](https://github.com/AgenticsWorks/AgentPeerChat) · [Microsoft Agent Framework](https://github.com/microsoft/agent-framework) · [LangGraph](https://github.com/langchain-ai/langgraph) · [CrewAI](https://github.com/crewAIInc/crewAI) · [AutoGen](https://github.com/microsoft/autogen) · [OpenHands](https://github.com/OpenHands/OpenHands) · [OpenClaw](https://github.com/openclaw/openclaw)

- [OpenAI: ChatGPT developer mode](https://developers.openai.com/api/docs/guides/developer-mode)
- [Claude: custom connectors via remote MCP](https://www.claude.com/docs/connectors/custom/remote-mcp)
- [xAI: Remote MCP tools](https://docs.x.ai/developers/tools/remote-mcp)
- [Gemini CLI: MCP servers](https://github.com/google-gemini/gemini-cli/blob/main/docs/tools/mcp-server.md)
- [A2A v1.0: Agent discovery](https://a2a-protocol.org/v1.0.0/topics/agent-discovery/)

Not reachable during research: Anthropic's support article on custom connectors (site error) and the A2A spec landing page (blocked). The Claude docs page above covered the same ground.
