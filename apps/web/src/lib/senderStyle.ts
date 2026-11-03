/** One visual identity per sender: color, initial and avatar shape (color is never the only cue). */
export interface SenderStyle {
  key: "claude" | "gpt" | "grokbot" | "grok" | "coordinator" | "owner" | "other";
  color: string;
  initial: string;
  shape: "circle" | "diamond" | "square";
}

const STYLES: Record<SenderStyle["key"], Omit<SenderStyle, "key">> = {
  claude: { color: "#E8955A", initial: "C", shape: "circle" },
  gpt: { color: "#34C79A", initial: "G", shape: "circle" },
  grokbot: { color: "#A78BFA", initial: "X", shape: "diamond" },
  grok: { color: "#A78BFA", initial: "X", shape: "circle" },
  coordinator: { color: "#8B95A5", initial: "⚙", shape: "square" },
  owner: { color: "#4C9AFF", initial: "N", shape: "circle" },
  other: { color: "#9AA4B2", initial: "?", shape: "square" },
};

/** Identity from trusted sender metadata (kind and display name), never from message text. */
export function senderStyle(sender: { kind: string; display_name: string }): SenderStyle {
  const name = sender.display_name.toLowerCase().replace(/[^a-z]/g, "");
  let key: SenderStyle["key"] = "other";
  if (sender.kind === "system") key = "coordinator";
  else if (sender.kind === "owner" || sender.kind === "human") key = "owner";
  else if (sender.kind === "external") key = name.startsWith("grok") ? "grokbot" : "other";
  else if (name.startsWith("claude")) key = "claude";
  else if (name.startsWith("gpt") || name.startsWith("chatgpt")) key = "gpt";
  else if (name.startsWith("grok")) key = "grok";
  const style = { key, ...STYLES[key] };
  if (key === "owner" || key === "other") {
    const first = sender.display_name.trim()[0];
    if (first) style.initial = first.toUpperCase();
  }
  return style;
}

/** Color with alpha for tinted bubbles, e.g. tint("#E8955A", 0.12). */
export function tint(hex: string, alpha: number): string {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`;
}
