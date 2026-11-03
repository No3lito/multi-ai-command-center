/** Identity comes only from platform sender metadata, never message text. */
export interface Speaker {
  id?: string;
  kind: string;
  display_name: string;
}

export interface SenderStyle {
  key: "claude" | "gpt" | "grokbot" | "grok" | "coordinator" | "owner" | "other";
  color: string;
  initial: string;
  shape: "circle" | "diamond" | "square";
}

export function speakerId(sender: Speaker): string {
  return `${sender.kind}:${sender.id ?? sender.display_name}`;
}

export function senderStyle(sender: Speaker): SenderStyle {
  const name = sender.display_name.toLowerCase().replace(/[^a-z]/g, "");
  let key: SenderStyle["key"] = "other";
  if (sender.kind === "system") key = "coordinator";
  else if (sender.kind === "owner" || sender.kind === "human") key = "owner";
  else if (sender.kind === "external") key = name.startsWith("grok") ? "grokbot" : "other";
  else if (name.startsWith("claude")) key = "claude";
  else if (name.startsWith("gpt") || name.startsWith("chatgpt")) key = "gpt";
  else if (name.startsWith("grok")) key = "grok";
  const colors = {
    owner: "var(--speaker-owner)",
    claude: "var(--speaker-claude)",
    gpt: "var(--speaker-gpt)",
    coordinator: "var(--speaker-system)",
    grok: "var(--speaker-blue)",
    grokbot: "var(--speaker-violet)",
    other: "var(--speaker-green)",
  };
  return {
    key,
    color: colors[key],
    initial: sender.display_name.trim().split(/\s+/).map((part) => part[0]).slice(0, 2).join("").toUpperCase() || "?",
    shape: "circle",
  };
}

const AVAILABLE = [
  "var(--speaker-blue)",
  "var(--speaker-violet)",
  "var(--speaker-green)",
  "var(--speaker-rose)",
];

/** Extend a room-local registry without changing identities already displayed. */
export function assignSpeakerStyles(
  senders: readonly Speaker[],
  previous: ReadonlyMap<string, SenderStyle> = new Map(),
): Map<string, SenderStyle> {
  const result = new Map(previous);
  const used = new Set([...result.values()].map((style) => style.color));
  // Reserve fixed identities before allocating other participants.
  const ordered = [...senders].sort((a, b) => {
    const priority = (sender: Speaker) =>
      ["owner", "claude", "gpt", "coordinator"].includes(senderStyle(sender).key) ? 0 : 1;
    return priority(a) - priority(b);
  });
  for (const sender of ordered) {
    const id = speakerId(sender);
    if (result.has(id)) continue;
    const style = senderStyle(sender);
    const fixed = ["owner", "claude", "gpt", "coordinator"].includes(style.key);
    let color = fixed && !used.has(style.color) ? style.color : AVAILABLE.find((value) => !used.has(value));
    if (!color) {
      let index = result.size;
      do {
        color = `hsl(${(index++ * 137.508) % 360} 55% 32%)`;
      } while (used.has(color));
    }
    result.set(id, { ...style, color });
    used.add(color);
  }
  return result;
}

/** Supports both legacy hex callers and CSS-variable speaker tokens. */
export function tint(color: string, alpha: number): string {
  if (!/^#[0-9a-f]{6}$/i.test(color)) {
    return `color-mix(in srgb, ${color} ${alpha * 100}%, transparent)`;
  }
  const n = parseInt(color.slice(1), 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`;
}
