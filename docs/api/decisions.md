# Decision cards

The owner answers decisions on the dashboard with one click. Approving starts the work the agents already prepared, so there is no copying of goals between screens and no nudging of agents.

## How a decision is raised

- The decision brief (see [`files-and-briefs.md`](files-and-briefs.md)) ends with a fenced ` ```decisions ` block: a JSON array with one object per "Waiting on you" item.
- Each object has `question`, `recommendation`, `cost` (or `"unknown"`), `on_approve` and `on_more_info`.
  - `on_approve`: `{workflow: "review" | "build" | "collab" | "none", worker: name | null, goal, attachments: [paths]}`.
  - `on_more_info`: `{workflow, worker, goal}`. It defaults to `collab`.
- The block is removed from the chat message and from `Run.brief`. It is stored as `Decision` rows (table `decisions`, migration 0010), with at most 10 per brief.
- If the block is missing or invalid, each "Waiting on you" bullet becomes a decision with `on_approve.workflow = "none"`.
- The brief's author is told never to propose real trades, moving funds or changing live settings.

## API (owner session)

- `GET /api/rooms/{room_id}/decisions?status=pending|decided|all&limit=50`
  - Returns `DecisionOut[]`, pending first, then newest.
  - Fields: `id, room_id, run_id, run_goal (first line), question, recommendation, cost, on_approve, on_more_info, status, owner_note, decided_at, follow_up_run_id, created_at`.
- `POST /api/decisions/{id}/answer` with `{answer: "approve" | "decline" | "more_info" | "dismiss", note?: string (max 2,000 characters), budget_usd?: number (more than 0, at most 5)}`
  - Owner only (403 otherwise). Returns 409 if the decision is already answered.
  - **approve / more_info:** starts the prepared follow-up run at once. Its goal is the agents' goal, plus the owner's verdict and note. It reuses the source run's planner and critic, re-reads the attached files, writes its own brief, and has a budget of `budget_usd`, or else the larger of the source run's budget and $0.50.
    - If the named worker isn't an active member of the room, the run falls back to a plan & review by Claude and GPT.
    - `workflow: "none"` starts nothing.
  - **decline / dismiss:** records the answer. Nothing runs.
  - Every answer posts a Coordinator message in the room (for example "Owner APPROVED: …", with the note), so every agent sees it. It also writes the audit record `decision.answer`.
  - Returns `{decision: DecisionOut, follow_up_run: RunOut | null}`.

## MCP (external agents such as Grok Bot)

- `get_decisions(room_id, limit=20)` returns the room's decisions, newest first: `{id, question, status, owner_note, decided_at, follow_up_run_id}`.
- The server instructions tell agents to work only within approved decisions and their notes.

## Dashboard

- The **Decisions** panel shows one card per pending decision. Each card has the question, the recommendation, the cost, and "If approved: …", in plain words.
- Card actions:
  - **Approve**, **Need more info**, **Decline** and **Dismiss**.
  - Optionally, a note or limit, and a budget for the follow-up run.
- A **Recently decided** list shows the last five answers, with notes and whether a follow-up run started.
- Simulated mode: a simulated brief raises one labelled example decision (`workflow: "none"`), so the buttons can be tried at no cost.
