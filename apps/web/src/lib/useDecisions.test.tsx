import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { Decision, Run } from "./types";
import { run } from "@/test/fixtures";
import { ROOM_A } from "@/test/fakeWebSocket";
import { replaceDecision, useDecisions } from "./useDecisions";

const d = (id: string, over: Partial<Decision> = {}): Decision => ({
  id,
  room_id: ROOM_A,
  run_id: "run_1",
  run_goal: "g",
  question: `q ${id}`,
  recommendation: null,
  cost: null,
  on_approve: { workflow: "none", worker: null, goal: "" },
  on_more_info: { workflow: "collab", worker: null, goal: "" },
  status: "pending",
  owner_note: null,
  decided_at: null,
  follow_up_run_id: null,
  created_at: "2026-11-02T12:00:00Z",
  ...over,
});

describe("replaceDecision", () => {
  it("replaces in place and keeps order", () => {
    const next = replaceDecision([d("a"), d("b")], d("b", { status: "approved" }));
    expect(next.map((x) => [x.id, x.status])).toEqual([
      ["a", "pending"],
      ["b", "approved"],
    ]);
  });
});

describe("useDecisions", () => {
  it("loads, reloads when a brief appears, and applies answers", async () => {
    const client = {
      listDecisions: vi.fn().mockResolvedValue([d("a")]),
      answerDecision: vi.fn().mockResolvedValue({ decision: d("a", { status: "declined" }), follow_up_run: null }),
    };
    let runs: Run[] = [run({ brief: null })];
    const { result, rerender } = renderHook(() => useDecisions(ROOM_A, runs, { client }));
    await waitFor(() => expect(result.current.decisions).toHaveLength(1));
    expect(client.listDecisions).toHaveBeenCalledTimes(1);

    runs = [run({ brief: "**Bottom line:** x", updated_at: "2026-11-02T12:05:00Z" })];
    rerender();
    await waitFor(() => expect(client.listDecisions).toHaveBeenCalledTimes(2));

    await act(async () => {
      await result.current.answer("a", { answer: "decline" });
    });
    expect(client.answerDecision).toHaveBeenCalledWith("a", { answer: "decline" });
    expect(result.current.decisions[0]!.status).toBe("declined");
  });
});
