# AGENTS.md

Shared instructions for every AI system working on this repository: Claude, ChatGPT/Codex, Grok, Gemini, local models, and any other coding or review agent. Read this whole file before doing anything.

## Project in one paragraph

Multi-AI Command Center is a locally controlled platform where multiple independent AI systems communicate, collaborate, delegate and build software together under a human operator. It must never depend on a single AI provider. The owner, Noel Rodriguez, makes all final decisions.

## Current phase

**Phase 2 is in progress, delivered as small working milestones (A to D).** The architecture (Revision 1) is approved and merged. Current status, what works, and blockers: [`docs/status.md`](docs/status.md).

- Implementation work is allowed on branches, one milestone or topic per branch. Nothing merges to `main` without the owner's approval.
- Follow the approved architecture: [`docs/phase-1-technical-discovery.md`](docs/phase-1-technical-discovery.md). API contracts live in [`docs/api/`](docs/api/); the shared message schema is [`packages/protocol/ccmp.schema.json`](packages/protocol/ccmp.schema.json).
- Prefer working, tested code over new planning documents.
- Disagree openly. If you think a decision is wrong, say so with evidence in an issue or PR.

## How to contribute

1. **Work on a branch, never on `main`.** Name it `agent/<your-name>/<short-topic>`, for example `agent/grok/review-security-model`.
2. **Open a pull request.** Only the owner merges to `main`.
3. **Say who you are.** Start the PR title with your system in brackets, for example `[ChatGPT] Review provider adapter design`, and state the model if you know it.
4. **One topic per PR.** Keep changes small enough to review.
5. **Do not edit files another open PR is changing** without saying so in that PR first.
6. **Label claims.** Mark anything as *verified* (you checked a source or ran it) or *recommendation* (your judgment). Link sources.

## Hard rules

- **No secrets.** Never commit API keys, tokens, passwords or `.env` files. Use `.env.example` with placeholder values only.
- **No protected health information.** This project is separate from any healthcare data. Do not add real patient, claims or provider data, even as test fixtures.
- **No copying protected code.** Reuse only code whose license allows it, with attribution. The researched projects are MIT-licensed; keep their notices if you reuse code.
- **Never claim something works without testing it.** Do not substitute mocks for real integrations without saying so.
- **Destructive, costly or privileged actions** (deleting data, deployments, credential changes, spending money) always need the owner's explicit approval.

## Engineering standards (from Phase 2 on)

- TypeScript strict mode; Python type annotations.
- Automated tests for every feature (Pytest, Vitest, Playwright).
- Environment-based configuration, pinned dependencies, structured logging.
- Document interfaces well enough that another agent can continue the work.

## Repository layout (planned)

```
apps/web/          Next.js dashboard
backend/           Python FastAPI backend (api, orchestrator, workers, execution, providers, policy, memory, db)
packages/protocol/ CCMP message schema (JSON Schema -> Pydantic + TypeScript)
infrastructure/    Docker and Compose files
docs/              Architecture, decisions, runbooks
```
