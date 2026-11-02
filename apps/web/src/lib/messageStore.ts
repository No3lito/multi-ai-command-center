import type { Message } from "./types";

/**
 * Merge incoming messages into an already sorted list.
 * Deduplicates by `id` (a message can arrive from GET, the socket and a POST
 * response) and keeps the result sorted ascending by `seq`.
 */
export function mergeMessages(existing: readonly Message[], incoming: readonly Message[]): Message[] {
  if (incoming.length === 0) return existing as Message[];
  const byId = new Map<string, Message>();
  for (const m of existing) byId.set(m.id, m);
  let changed = false;
  for (const m of incoming) {
    if (!byId.has(m.id)) {
      byId.set(m.id, m);
      changed = true;
    }
  }
  if (!changed) return existing as Message[];
  return Array.from(byId.values()).sort((a, b) => a.seq - b.seq || a.id.localeCompare(b.id));
}

/** Minimal structural check for frames coming off the wire. */
export function isMessage(value: unknown): value is Message {
  if (!value || typeof value !== "object") return false;
  const m = value as Partial<Message>;
  return (
    typeof m.id === "string" &&
    typeof m.seq === "number" &&
    Number.isFinite(m.seq) &&
    typeof m.room_id === "string" &&
    typeof m.created_at === "string" &&
    !!m.sender &&
    typeof m.sender.display_name === "string" &&
    !!m.body &&
    typeof m.body.text === "string"
  );
}
