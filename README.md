# Multi-AI Command Center

A local-first, model-agnostic platform where Claude, ChatGPT, Grok, Gemini and locally hosted models collaborate as independent, interchangeable agents: chatting in shared rooms, delegating tasks, reviewing each other's work and building software together, under one human operator's control.

**Owner:** Noel Rodriguez
**Status:** Phase 1 (Technical Discovery) complete. Architecture awaiting owner approval. No application code yet.

## Start here

| If you are... | Read |
| --- | --- |
| Any AI collaborator (ChatGPT, Grok, Gemini, Claude, Codex, etc.) | [`AGENTS.md`](AGENTS.md), then the Phase 1 report |
| Claude Code | [`CLAUDE.md`](CLAUDE.md) |
| A human reviewer | [`docs/phase-1-technical-discovery.md`](docs/phase-1-technical-discovery.md) |

## What it will do

- **Multi-AI chatroom:** humans and agents from different providers in one real-time room, with persistent history.
- **Autonomous workforce:** a coordinator plans work, assigns it to role-based agents (architect, developer, reviewer, QA, security, docs), and asks the human to approve consequential steps.
- **Cross-AI interoperability:** external AI clients join through a Command Center MCP gateway; built-in agents call providers through official SDKs.
- **Safety by design:** deny-by-default permissions, sandboxed execution, budgets and turn limits, an emergency stop, and a hash-chained audit log.

## Proposed stack (pending approval)

Next.js + TypeScript + Tailwind · Python + FastAPI · PostgreSQL + pgvector · WebSockets · Docker Compose · official Anthropic, OpenAI, xAI, Google GenAI and Ollama SDKs.

## Roadmap

| Phase | Scope | Status |
| --- | --- | --- |
| 1 | Technical discovery and architecture | Done; Revision 1 under review ([#1](https://github.com/No3lito/multi-ai-command-center/issues/1)) |
| 2 | Minimum viable chatroom: two providers, minimal MCP gateway, concurrency, security controls, approval gate | Not started |
| 3 | Agent roles, tasks, handoffs, more providers, orchestration engine evaluation | Not started |
| 4 | Workflow engine, sandbox, code review loops, audit | Not started |
| 5 | Customization, memory, MCP gateway, A2A | Not started |
| 6 | Production hardening | Not started |

## License

No license yet. All rights reserved by the owner until one is chosen.
