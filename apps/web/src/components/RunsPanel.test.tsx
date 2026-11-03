import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { run } from "@/test/fixtures";
import { RunsPanel, visibleRuns } from "./RunsPanel";

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

describe("Try again", () => {
  const panel = (runs: ReturnType<typeof run>[], onTryAgain = vi.fn(async () => undefined)) => {
    render(
      <RunsPanel
        hasRoom
        runs={runs}
        loaded
        error={null}
        agentName={() => "Claude"}
        onCancel={vi.fn()}
        onRetry={vi.fn()}
        onTryAgain={onTryAgain}
      />,
    );
    return onTryAgain;
  };

  it("restarts a failed code job with one click", async () => {
    const onTryAgain = panel([run({ id: "run_code", kind: "code", status: "failed" })]);
    await userEvent.setup().click(screen.getByTestId("run-try-again"));
    expect(onTryAgain).toHaveBeenCalledWith("run_code");
  });

  it("is not offered for other runs or for code jobs that finished well", () => {
    panel([
      run({ id: "run_a", kind: "collab", status: "failed" }),
      run({ id: "run_b", kind: "code", status: "completed" }),
    ]);
    expect(screen.queryByTestId("run-try-again")).toBeNull();
  });
});
