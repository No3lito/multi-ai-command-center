# Phase 1 dashboard inventory

Source inspection only: the supplied Shell, RoomView, Sidebar, RightPanel,
MessageList, Composer, Markdown, senderStyle, and stylesheet files.
Nested panel implementations were not supplied; their existing components,
props, and workflows are retained without rewriting their internal controls.

## Existing features, labels, and controls retained

- Shell: room loading/error/ready states; URL room selection and browser
  back/forward; General-room fallback; room creation and sorted room list;
  "Skip to message composer"; "Close panel"; Escape closes drawers.
- Sidebar: logo and "Multi-AI Command Center"; "Rooms", "New project",
  creation modal/form; "Loading rooms...", "Retry", empty-room guidance;
  room names, selection, active-room indication; principal name, initial,
  kind, and "Sign out".
- Room header: "Show rooms"; room name and # marker; project title/path;
  member avatars/count; "No room selected"; "New goal"; connection status;
  "Show room details".
- Room states: "No rooms yet", "Pick a room", "Loading rooms",
  "Room not found", "Could not load this room", "Could not load messages",
  "Try again"; fatal-stream alert.
- Details: "Room details"; resizable panel with persisted width, pointer and
  arrow-key resizing; tabs, badges, Summary, Decisions, Inbox, Runs, History,
  Project, Agents, Usage, Connections; member names/kinds; connection
  "status", "last seq", "room", "n/a" and loading/empty states.
- Workflow actions retained through existing components: decisions and
  follow-up runs, inbox filing, project selection, agent membership,
  connection management, run cancellation/wrap-up/retry, archived history.
- New-goal modal: room/project context, agents/externals, file listing and
  suggestions, code-job availability, create-run and modal close.
- Messages: loading/empty states; safe Markdown; sender identity and kind;
  provider/model, SIMULATED disclosure, non-chat kind, timestamp/full-time
  title, sequence, correlation/reply metadata; token counts and costs.
- Finished-run folds: status, kind, spend, verdict, title, brief,
  "Show conversation", "Hide conversation", "Archive", archive errors.
- Outbox: "You", "Sending...", "Not sent", error text, "Retry", "Discard";
  existing idempotent retries remain owned by useOutbox.
- Composer: accessible room-specific label; Enter send, Shift+Enter newline;
  IME protection; empty/disabled/length limits; "Send"; mention discovery,
  filtering, provider/model details, arrow navigation, Enter/Tab selection,
  Escape dismissal, caret restoration; length-error hint.
- Markdown: safe links, textual HTML/images, GFM lists/tables, scrolling code,
  long-answer folding, "Show more"/"Show less".
- Accessibility: message log, polite announcements, keyboard scroll target,
  skip link, focus outlines, drawer visibility and reduced-motion support.

## Intentional presentation changes

- Light theme replaces the dark default; no Phase 2 animation is added.
- Message-card badges say You / AI / System; the existing principal-kind
  badge and underlying kind remain available as metadata.
- "Jump to latest" becomes "New messages ↓".
- The composer gains the required team-message hint while retaining mention
  instructions and its room-specific accessible label.
- Header avatars move to a named participant strip.
- Populated task/progress information is collapsible; no synthetic status
  or progress is introduced. Setup and other management panels remain.
- Sender name, initials, role, and metadata identify speakers without color.

## Verification still required

Run the web test suite and type/lint checks. Review populated desktop and
360px previews with Noel, at least three AIs, a Coordinator event, long code,
and failed delivery. Measure page overflow, inspect grayscale identities,
verify computed text/background AA contrast, and navigate all controls with
keyboard only. No browser or automated execution is claimed here.

The seven requested speaker colors are finite: overflow speakers receive
additional deterministic colors rather than silently reusing an occupied
palette slot. Those additional accent colors need visual review too.
