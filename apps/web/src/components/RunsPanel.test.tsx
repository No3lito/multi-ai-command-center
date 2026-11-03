import { describe, expect, it } from "vitest";
import { run } from "@/test/fixtures";
import { visibleRuns } from "./RunsPanel";

describe("visibleRuns", () => {
  it("shows active runs and the last 5 finished, never archived ones", () => {
    const done = Array.from({ length: 8 }, (_, i) => run({ id: `run_d${i}`, status: "completed" }));
    const runs = [
      run({ id: "run_live", status: "waiting" }),
      run({ id: "run_arch", status: "completed", archived_at: "x" }),
      ...done,
    ];
    const recent = visibleRuns(runs, false);
    expect(recent.shown.map((r) => r.id)).toEqual(["run_live", "run_d0", "run_d1", "run_d2", "run_d3", "run_d4"]);
    expect(recent.hidden).toBe(3);
    expect(visibleRuns(runs, true).shown).toHaveLength(9);
  });
});
