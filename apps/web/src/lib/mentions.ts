/** Helpers for "@DisplayName" mentions in the composer. Text is never parsed as HTML. */

export interface MentionCandidate {
  id: string;
  display_name: string;
}

export interface MentionQuery {
  /** Index of the "@" in the text. */
  start: number;
  /** Text typed after the "@", up to the caret. */
  query: string;
}

/**
 * The "@query" being typed at the caret, if any. The "@" must start the text
 * or follow whitespace, and the query cannot contain whitespace or another "@".
 */
export function findMentionQuery(text: string, caret: number): MentionQuery | null {
  const before = text.slice(0, Math.max(0, Math.min(caret, text.length)));
  const match = /(^|\s)@([^\s@]*)$/.exec(before);
  if (!match) return null;
  const query = match[2] ?? "";
  return { start: before.length - query.length - 1, query };
}

/** Candidates whose name starts with the query first, then those that contain it. */
export function filterCandidates<T extends MentionCandidate>(candidates: readonly T[], query: string, max = 8): T[] {
  const q = query.toLowerCase();
  const starts: T[] = [];
  const contains: T[] = [];
  for (const c of candidates) {
    const name = c.display_name.toLowerCase();
    if (name.startsWith(q)) starts.push(c);
    else if (q && name.includes(q)) contains.push(c);
  }
  return [...starts, ...contains].slice(0, max);
}

/** Replace the "@query" at `at` with "@DisplayName " and return the new text and caret. */
export function insertMention(
  text: string,
  at: MentionQuery,
  caret: number,
  name: string,
): { text: string; caret: number } {
  const inserted = `@${name} `;
  const end = Math.max(caret, at.start + 1 + at.query.length);
  const rest = text.slice(end).replace(/^ /, "");
  return { text: text.slice(0, at.start) + inserted + rest, caret: at.start + inserted.length };
}

const escapeRegExp = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/** True when "@DisplayName" appears in the text as a whole mention (case-insensitive). */
export function hasMention(text: string, displayName: string): boolean {
  if (!displayName) return false;
  const re = new RegExp(`(^|[^\\w@])@${escapeRegExp(displayName)}(?![\\w])`, "i");
  return re.test(text);
}

/** Ids of candidates whose "@DisplayName" is still present in the text, in candidate order, deduplicated. */
export function extractMentions(text: string, candidates: readonly MentionCandidate[]): string[] {
  const ids: string[] = [];
  // Longer names first so "@Claude Opus" is not also counted as "@Claude" when both exist.
  const byLength = [...candidates].sort((a, b) => b.display_name.length - a.display_name.length);
  let remaining = text;
  const found = new Set<string>();
  for (const c of byLength) {
    if (hasMention(remaining, c.display_name)) {
      found.add(c.id);
      const re = new RegExp(`(^|[^\\w@])@${escapeRegExp(c.display_name)}(?![\\w])`, "gi");
      remaining = remaining.replace(re, "$1");
    }
  }
  for (const c of candidates) if (found.has(c.id) && !ids.includes(c.id)) ids.push(c.id);
  return ids;
}
