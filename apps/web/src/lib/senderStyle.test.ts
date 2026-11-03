import { describe, expect, it } from "vitest";
import { senderStyle, tint } from "./senderStyle";

describe("senderStyle", () => {
  it("gives each sender its own color, initial and shape", () => {
    expect(senderStyle({ kind: "agent", display_name: "Claude" })).toMatchObject({ key: "claude", color: "#E8955A" });
    expect(senderStyle({ kind: "agent", display_name: "GPT" })).toMatchObject({ key: "gpt", color: "#34C79A" });
    expect(senderStyle({ kind: "external", display_name: "Grok Bot" })).toMatchObject({
      key: "grokbot",
      shape: "diamond",
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

  it("tints colors", () => expect(tint("#E8955A", 0.12)).toBe("rgba(232, 149, 90, 0.12)"));
});
