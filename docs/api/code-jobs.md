# Code jobs

Claude and GPT change the Command Center's own code together. One writes, the other reviews, the repository's automatic tests (CI) run, and the owner gets one card: merge the pull request or not. Nothing reaches `main` without that click.

## Turning it on

Code jobs are off until `GITHUB_TOKEN` is set in `.env`. Use a **fine-grained** token limited to one repository (`CODE_REPO`, default `No3lito/multi-ai-command-center`):

| Permission | Access |
| --- | --- |
| Contents | Read and write |
| Pull requests | Read and write |
| Actions | Read |
| Metadata | Read (always on) |

`CODE_JOB_BUDGET_USD` (default 3.00) caps one job. It counts toward `LIVE_BUDGET_USD`.

## How a job runs (run kind `code`)

| Step | Who | What happens |
| --- | --- | --- |
| `scope` | writer | Sees the repository's file list on the default branch and picks up to 15 files to read. |
| `write` | writer | Writes edit blocks. They are applied all-or-nothing, committed to `agent/command-center/<topic>-<id>`, and a pull request opens, titled `[Writer + Reviewer] …`. |
| `ci` | GitHub | The job waits for every workflow run on that commit (up to `CODE_CI_WAIT_MINUTES`, default 25). The worker is free between one-minute slices. |
| `review` | reviewer | Gets the diff and the test result and ends with `VERDICT: APPROVE` or `VERDICT: CHANGES`. |
| `fix` | writer | Gets the review, the failing jobs with the end of their logs, and any edits that could not apply. Then `ci` and `review` run again. At most 2 fix rounds. |
| `final` | Coordinator | Posts the result and raises one decision card. |

Writer and reviewer take turns: Claude writes on even-numbered jobs, GPT on odd ones.

**The card:** approve merges the pull request (squash) on GitHub, but only if it is still open, is a code job branch, targets the default branch, and its head is still the commit that was reviewed (the merge call pins that commit). Decline closes it; "Need more info" ("Send it back") starts another code job on the same branch and pull request, with the owner's note as a requirement. If GitHub refuses the merge, the card stays open and the error is shown.

## Rules the job enforces (verified against a fake GitHub in tests, not yet against real GitHub)

- Never changed: `.github/` (any case), `.git` folders, `CODEOWNERS`, `.env` files (except `.env.example`), key files, the generated `docker-compose.override.yml`, and anything outside the repository. Paths must be plain ASCII with no empty, `.` or `..` parts.
- The writer can only edit or delete files it was shown, or create new ones. A SEARCH text must match exactly once.
- `[skip ci]` and similar markers are removed from commit messages and titles. A commit with no CI run is reported as **not verified**, and the card does not recommend merging it.
- If a job stops after its pull request opened (edits failing in the last round, an interrupted step), it still ends with the card, so no pull request is left without a decision.
- Any edit that cannot apply means nothing is committed; the errors go back to the writer.
- Every model call goes through the budget (job, then instance-wide cap) before it is sent. Code jobs are not counted in the $2 follow-up chain budget; each send-back needs the owner's click and has its own job budget (a dollar cap in the note lowers it).
- Without a token, the dashboard shows the option as off with the reason, and the API returns `409 code_jobs_off`.

## Waiting for the models

Code job steps wait longer than chat answers: picking files 4 minutes, writing 10 minutes, reviewing 6 minutes (the first real job failed at the 90-second chat default). A timed-out call is still counted as billed.

## Trying again

`POST /api/runs/{id}/try-again` (dashboard: **Try again** on a failed, budget-stopped or cancelled code job) starts a new job with the same goal, writer, reviewer and agreed spec, and a fresh job budget. With a pull request already open it continues it (tests, then review); otherwise it starts by picking files. Each job can be started again once.

## Starting one

- **Dashboard:** New goal → Workflow → *Code change*.
- **From a decision:** a brief can propose `"on_approve": {"workflow": "code", "goal": "..."}` when the room lists the coding team. Code jobs are not limited by the follow-up round limit; they have their own budget.
- **API:** `POST /api/rooms/{room_id}/runs` with `"workflow": "code"`, `planner_id` and `critic_id` set to the Claude and GPT agents. The server picks who writes. `GET /api/code-jobs` says whether jobs are on.

## Run and decision fields

- `RunOut.code_pr`: `{number, url, title}` once the pull request exists.
- `DecisionOut.code_pr`: set on the merge card.
- `DecisionAnswerOut.code_result`: what happened on GitHub (merged or closed), also posted in the room.

## Not done yet

- GitHub's automatic tests do not run the code on the owner's computer; after merging, the owner rebuilds (`docker compose up -d --build`).
- Files over 60,000 characters are not offered for editing.
