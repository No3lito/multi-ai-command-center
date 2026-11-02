import { describe, expect, it } from "vitest";
import { extractMentions, filterCandidates, findMentionQuery, insertMention } from "./mentions";

const A = { id: "agt_a", display_name: "Claude" };
const B = { id: "agt_b", display_name: "GPT" };
const C = { id: "agt_c", display_name: "Claude Opus" };

describe("mentions", () => {
  it("finds the @query at the caret only at a word start", () => {
    expect(findMentionQuery("hi @Cl", 6)).toEqual({ start: 3, query: "Cl" });
    expect(findMentionQuery("@", 1)).toEqual({ start: 0, query: "" });
    expect(findMentionQuery("mail me@host", 12)).toBeNull();
    expect(findMentionQuery("@Claude hi", 10)).toBeNull();
  });

  it("filters by prefix, then substring, case-insensitively", () => {
    expect(filterCandidates([A, B], "g").map((c) => c.id)).toEqual(["agt_b"]);
    expect(filterCandidates([A, B], "").map((c) => c.id)).toEqual(["agt_a", "agt_b"]);
    expect(filterCandidates([B, C], "opus").map((c) => c.id)).toEqual(["agt_c"]);
  });

  it("inserts @DisplayName with a trailing space", () => {
    const r = insertMention("hey @cl", { start: 4, query: "cl" }, 7, "Claude");
    expect(r).toEqual({ text: "hey @Claude ", caret: 12 });
  });

  it("extracts ids for names still in the text, case-insensitive and whole-word", () => {
    expect(extractMentions("@claude and @GPT, thoughts?", [A, B])).toEqual(["agt_a", "agt_b"]);
    expect(extractMentions("@Claudette hi", [A])).toEqual([]);
    expect(extractMentions("no mentions", [A, B])).toEqual([]);
    expect(extractMentions("email a@Claude", [A])).toEqual([]);
    expect(extractMentions("@Claude Opus only", [A, C])).toEqual(["agt_c"]);
    expect(extractMentions("@Claude Opus and @Claude", [A, C])).toEqual(["agt_a", "agt_c"]);
  });
});
