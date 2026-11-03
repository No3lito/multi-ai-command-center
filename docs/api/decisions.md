# Decision cards

The owner answers decisions on the dashboard with one click. Approving starts the work the agents already prepared, so there is no copying of goals between screens and no nudging of agents.

## Conclude, don't loop

- **Verdict:** every brief starts with `**Verdict:** Done | Blocked | Needs you` and the answer in one sentence. It's stored as `Run.verdict` (`done`, `blocked` or `needs_you`) and shown as a pill on runs, folded run cards, the latest conclusion and History.
- **What reaches the owner:** "Waiting on you" may only hold decisions that spend money beyond the run, touch anything live or irreversible, or change direction. Agents decide everything else and list it under Decided. They never ask the owner who should do work.
- **Who can do work:** the brief's author gets the real list of who can act in the room and what each can and cannot do (`describe_executors`). Claude and GPT write text only. Grok Bot uses its own tools. Changing the Command Center's code needs a coding agent, which never appears in the room.
- **No silent fallbacks:** if a follow-up's worker isn't in the room, or a limit is reached, nothing starts. The answer is still recorded, and the reason is returned as `DecisionAnswerOut.no_run_reason` and posted in the room ("Nothing was started: …"). Pending cards show it ahead of time as `cannot_run_reason`.
- **Round limit:** follow-ups form a chain (`Run.chain_root_id`, `Run.chain_depth`). There are at most `MAX_ROUNDS` = 2 follow-up rounds. The last round is told to give a final recommendation, its decisions can't start more runs, and cards from it show **Final round**.
- **Chain budget:**
  - A chain shares `CHAIN_BUDGET` = $2.00. A follow-up's budget is the smallest of: the requested budget (or the default), any dollar cap in the owner's note ("under $1.00", "max $0.50"; `note_cap`), and what's left of the chain budget.
  - Under $0.10 left: nothing starts.
- **Lean follow-ups:** a follow-up carries only `previous-run/<id>.md` (the previous brief plus its final message) and any files its plan names, not every file the previous run had.
- **Lean context:** steps of plan, build and review runs read their own run's messages plus the owner's last 10 chat messages outside runs (`lean=True`). Reply runs still see the room.
- **Owner's notes:** every sentence is a requirement ("finalize" means conclude now).
- **Wrap it up:** `POST /api/runs/{id}/wrap-up` (owner, active plan, build or review runs) sets `wrap_up`. The engine skips the remaining steps, including a wait for Grok Bot, and the lead writes a concluding brief.

## How a decision is raised

- The decision brief (see [`files-and-briefs.md`](files-and-briefs.md)) ends with a fenced ` ```decisions ` block: a JSON array with one object per "Waiting on you" item.
- Each object has `question`, `why` (two or three plain-language sentences), `recommended` (`approve`, `decline` or `more_info`), `recommendation` (that answer and the reason), `suggested_note` (conditions, caps and checks, written as an instruction to the agents), `cost` (or `"unknown"`), `on_approve` and `on_more_info`.
  - If `recommended` is missing, it is inferred from how `recommendation` starts ("Approve…", "More info…", "Decline…" or "Hold…").
  - `on_approve`: `{workflow: "review" | "build" | "collab" | "none", worker: name | null, goal, attachments: [paths]}`.
  - `on_more_info`: `{workflow, worker, goal}`. It defaults to `collab`.
- The block is removed from the chat message and from `Run.brief`. It is stored as `Decision` rows (table `decisions`, migration 0010), with at most 10 per brief.
- If the block is missing or invalid, each "Waiting on you" bullet becomes a decision with `on_approve.workflow = "none"`.
- The brief's author is told never to propose real trades, moving funds or changing live settings.

## API (owner session)

- `GET /api/rooms/{room_id}/decisions?status=pending|decided|all&limit=50`
  - Returns `DecisionOut[]`, pending first, then newest.
  - Fields: `id, room_id, run_id, run_goal (first line), question, why, recommended, suggested_note, recommendation, cost, on_approve, on_more_info, status, owner_note, decided_at, follow_up_run_id, created_at`.
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

## Archive and history

- `POST /api/runs/{id}/archive` and `POST /api/runs/{id}/unarchive` (owner only): hide or show a finished run in the chat and the run list. Nothing is deleted. A run that is still active returns 409.
- `GET /api/rooms/{id}/history?q=&archived=include|only|exclude&limit=50` returns `{runs: RunOut[], decisions: DecisionOut[]}`, newest first.
  - Runs are finished workflow runs (not replies). Every word of `q` must match the goal or brief.
  - Decisions match on the question, the owner's note or `why`.
  - The search is case-insensitive, and `%` and `_` are matched literally.
- `RunOut.archived_at` is set while a run is archived.

## Dashboard

- The right panel has four tabs: **Decide** (the summary and the cards), **Runs** (active runs plus the last 5 finished, with "Show older"), **History** (search, past briefs, archive and unarchive) and **Setup** (agents, usage, connections, members).
- **Summary**, at the top of Decide: what finished since the owner last opened the room (per browser; otherwise the last 24 hours), how many decisions are waiting, what is in progress and who it is waiting for, and the spend so far.
- Each pending decision is a card with the question, "Why it matters", the recommendation, the cost and "If approved: …", in plain words.
  - The agents' suggested note is already filled in, and the owner can edit it.
  - **Do what they recommend** sends the recommended answer with the note in one click.
- Card actions:
  - **Approve**, **Need more info**, **Decline** and **Dismiss**.
  - Optionally, a note or limit, and a budget for the follow-up run.
- A **Recently decided** list shows the last five answers, with notes and whether a follow-up run started.
- **Chat:** each finished workflow run folds into one card in the chat, showing its goal, status, cost and bottom line, with **Show conversation** and **Archive**.
  - A run the owner watched in progress stays open after it finishes.
  - Owner messages, replies to @mentions and decision answers are never folded.
- **New goal:** a button in the room header opens the goal form in a pop-up.
- Simulated mode: a simulated brief raises one labelled example decision (`workflow: "none"`), so the buttons can be tried at no cost.
