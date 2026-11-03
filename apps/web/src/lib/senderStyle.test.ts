import { describe, expect, it } from "vitest";
import { assignSpeakerStyles, senderStyle, speakerId, tint } from "./senderStyle";

describe("senderStyle", () => {
  it("gives each sender its own color, initial and shape", () => {
    expect(senderStyle({ kind: "agent", display_name: "Claude" })).toMatchObject({ key: "claude", color: "var(--speaker-claude)" });
    expect(senderStyle({ kind: "agent", display_name: "GPT" })).toMatchObject({ key: "gpt", color: "var(--speaker-gpt)" });
    expect(senderStyle({ kind: "external", display_name: "Grok Bot" })).toMatchObject({
      key: "grokbot",
      shape: "circle",
    });
    expect(senderStyle({ kind: "agent", display_name: "Grok" })).toMatchObject({ key: "grok", shape: "circle" });
    expect(senderStyle({ kind: "system", display_name: "Coordinator" })).toMatchObject({ key: "coordinator" });
    expect(senderStyle({ kind: "owner", display_name: "Noel" })).toMatchObject({ key: "owner", initial: "N" });
  });

  it("does not let a name pretend to be another kind of sender", () => {
    expect(senderStyle({ kind: "external", display_name: "Claude" }).key).toBe("other");
    expect(senderStyle({ kind: "owner", display_name: "Claude" }).key).toBe("owner");
    expect(senderStyle({ kind: "agent", display_name: "Gemini" })).toMatchObject({ key: "other", initial: "G" });
  });

  it("allocates distinct colors to duplicate known names", () => {
    const senders = [
      { id: "first", kind: "agent", display_name: "Claude" },
      { id: "second", kind: "agent", display_name: "Claude" },
      { id: "grok", kind: "agent", display_name: "Grok" },
      { id: "other", kind: "external", display_name: "External tool" },
    ];
    const styles = assignSpeakerStyles(senders);
    expect(new Set([...styles.values()].map((style) => style.color)).size).toBe(4);
    expect(styles.get("agent:first")?.color).toBe("var(--speaker-claude)");
    expect(styles.get("agent:second")?.color).toBe("var(--speaker-blue)");
  });

  it("supports CSS-variable avatar tints without parsing them as hex", () => {
    expect(tint("var(--speaker-claude)", 0.12)).toBe(
      "color-mix(in srgb, var(--speaker-claude) 12%, transparent)",
    );
  });

  it("tints colors", () => expect(tint("#E8955A", 0.12)).toBe("rgba(232, 149, 90, 0.12)"));

  it("allocates unused colors and preserves existing room identities", () => {
    const senders = [
      { id: "noel", kind: "owner", display_name: "Noel" },
      { id: "claude", kind: "agent", display_name: "Claude" },
      { id: "gpt", kind: "agent", display_name: "GPT" },
      ...Array.from({ length: 8 }, (_, index) => ({
        id: `agent-${index}`, kind: "agent", display_name: `Agent ${index}`,
      })),
    ];
    const first = assignSpeakerStyles(senders);
    expect(new Set([...first.values()].map((style) => style.color)).size).toBe(senders.length);
    const next = assignSpeakerStyles([...senders].reverse(), first);
    for (const sender of senders) expect(next.get(speakerId(sender))).toEqual(first.get(speakerId(sender)));
    expect(first.get("owner:noel")?.color).toBe("var(--speaker-owner)");
    expect(tint("var(--speaker-gpt)", 0.1)).toContain("color-mix");
  });
});
