import { isRunActive, type Message, type Run } from "./types";

export type ChatItem =
  | { type: "message"; message: Message }
  | {
      type: "run";
      runId: string;
      /** Known run (from the run list); null for older runs outside the list. */
      run: Run | null;
      messages: Message[];
      /** First line of the Coordinator's first note, used when the run is unknown. */
      title: string;
    };

const RUN_ID = /^run_/;
const NOTE_KINDS = new Set<Message["kind"]>(["task.assign", "task.status", "task.result"]);

/** The owner's answer to a decision stays in the chat, outside any folded run. */
function isDecisionNote(m: Message): boolean {
  return typeof m.body.data?.decision_id === "string";
}

/**
 * Fold each finished workflow run (plan & review, design & build, review & improve) into one
 * chat item, in the place of its first message. Owner messages, replies to @mentions, decision
 * answers and runs still in progress stay as normal messages. Archived runs are left out.
 */
export function foldRuns(messages: readonly Message[], runs: readonly Run[]): ChatItem[] {
  const byId = new Map(runs.map((r) => [r.id, r]));
  const groups = new Map<string, Message[]>();
  for (const m of messages) {
    const id = m.correlation_id;
    if (!id || !RUN_ID.test(id) || isDecisionNote(m)) continue;
    const list = groups.get(id);
    if (list) list.push(m);
    else groups.set(id, [m]);
  }

  const foldable = new Set<string>();
  for (const [id, list] of groups) {
    const run = byId.get(id);
    if (run && isRunActive(run)) continue;
    if (run && run.kind === "reply") continue;
    // Workflow runs always carry Coordinator notes; replies to @mentions do not.
    if (!run && !list.some((m) => m.sender.kind === "system" && NOTE_KINDS.has(m.kind))) continue;
    foldable.add(id);
  }

  const items: ChatItem[] = [];
  const placed = new Set<string>();
  for (const m of messages) {
    const id = m.correlation_id;
    if (id && foldable.has(id) && !isDecisionNote(m)) {
      if (placed.has(id)) continue;
      placed.add(id);
      const run = byId.get(id) ?? null;
      if (run?.archived_at) continue;
      const list = groups.get(id) ?? [];
      const note = list.find((x) => x.sender.kind === "system");
      items.push({
        type: "run",
        runId: id,
        run,
        messages: list,
        title: (run?.goal ?? note?.body.text ?? "Earlier run").split("\n")[0]!.slice(0, 200),
      });
      continue;
    }
    items.push({ type: "message", message: m });
  }
  return items;
}
