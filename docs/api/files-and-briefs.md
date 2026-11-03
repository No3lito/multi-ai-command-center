# Attached files and decision briefs

## Attached files (read-only)

The owner can attach text files from one folder on their computer to a run, so Claude and GPT read the real files instead of a summary.

- **Setup:** set `FILES_FOLDER` in `.env` (for example `C:\Users\noelm\Trading-Review`). Docker mounts it read-only at `/shared` (`FILES_ROOT`). If it isn't set, attachments are off.
- **Browse:** `GET /api/files?path=<relative folder>` (owner only) returns `{enabled, path, entries[{name, path, type: dir|file, size, readable}], max_files, max_chars}`. Hidden files (`.env`, `.git`), links pointing outside the folder and paths with `..` are never offered or read.
- **Attach:** `POST /api/rooms/{id}/runs` with `"attachments": ["logs/LEARNING-LOG-full.md", "README.md"]`.
  - Only text files are accepted: .md, .txt, .csv, .tsv, .json, .jsonl, .yaml, .yml, .toml, .log, .py, .sql and .ini.
  - Each file must be under 5 MB, with at most `ATTACHMENT_MAX_FILES` files (10) and `ATTACHMENT_MAX_CHARS` characters in total (300,000).
  - Each file is read **once, when the run starts**, and stored with the run, so every step sees the same version.
- **Who sees them:** model agents (Claude, GPT). They see the files at the top of their prompt, each wrapped in a random per-request boundary and labeled as owner-chosen data, not instructions. The contents are sent to Anthropic and OpenAI with each reviewer step and count toward the spending cap. Connected external agents (Grok Bot) only see the file names.
- `Run.attachments`: `[{path, chars}]`.

## Decision briefs

Every collaboration, design & build and review run ends with a **brief** step, unless the run is created with `"brief": false`. The lead agent (the planner or lead reviewer) writes a short brief under these fixed headings:

**Bottom line**, **Decided**, **Done**, **Waiting on you**, **Next steps**, **Open risks**

- The brief is a normal chat message in the room. It is also stored as `Run.brief`.
- The "Waiting on you" items are parsed into `Run.pending_decisions`, an empty list when there are none.
- The dashboard's **Decisions** panel shows the latest bottom line, what is waiting on the owner, and every earlier brief.
- Output limit: 6,000 tokens, including Claude's thinking. Each brief typically costs a few cents.
