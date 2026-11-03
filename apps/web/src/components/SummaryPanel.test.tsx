import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import type { Decision, Usage } from "@/lib/types";
import { run } from "@/test/fixtures";
import { SummaryPanel, buildSummary, lastSeenFor, resetLastSeen } from "./SummaryPanel";

const NOW = Date.parse("2026-11-03T12:00:00Z");
const usage: Usage = {
  cap_usd: 10,
  spent_usd: 1.35,
  reserved_usd: 0,
  remaining_usd: 8.65,
  by_provider: [],
  simulated_calls: 0,
};
const pending = { id: "dec_1", status: "pending", question: "Approve the audit?", cost: "unknown" } as Decision;
const name = (id: string | null) => (id === "ext_g" ? "Grok Bot" : null);

describe("buildSummary", () => {
  it("lists what finished since the last visit, what waits, what runs and the spend", () => {
    const s = buildSummary({
      runs: [
        run({
          id: "run_new",
          status: "completed",
          finished_at: "2026-11-03T08:00:00Z",
          brief: "**Bottom line:** No edge.",
        }),
        run({ id: "run_old", status: "completed", finished_at: "2026-11-01T08:00:00Z" }),
        run({ id: "run_wait", status: "waiting", waiting_for: "ext_g" }),
        run({
          id: "run_arch",
          status: "completed",
          finished_at: "2026-11-03T09:00:00Z",
          archived_at: "2026-11-03T10:00:00Z",
        }),
      ],
      decisions: [pending],
      usage,
      since: Date.parse("2026-11-02T22:00:00Z"),
      now: NOW,
      agentName: name,
    });
    expect(s.finished.map((f) => f.line)).toEqual(["No edge."]);
    expect(s.waiting).toEqual([{ question: "Approve the audit?", cost: "unknown" }]);
    expect(s.active).toEqual([{ id: "run_wait", goal: "Create a basic login interface", waitingFor: "Grok Bot" }]);
    expect(s.spend).toEqual({ spent: 1.35, cap: 10, remaining: 8.65 });
  });

  it("renders plain lines", () => {
    render(<SummaryPanel runs={[]} decisions={[pending]} usage={usage} since={null} now={NOW} agentName={name} />);
    expect(screen.getByTestId("summary-panel")).toHaveTextContent("In the last 24 hours");
    expect(screen.getByTestId("summary-waiting")).toHaveTextContent("1 decision is waiting on you");
    expect(screen.getByTestId("summary-spend")).toHaveTextContent("Spent $1.35 of $10.00; $8.65 left.");
  });
});

describe("lastSeenFor", () => {
  beforeEach(() => {
    resetLastSeen();
    window.localStorage.clear();
  });
  it("returns the previous visit once per page load and records this one", () => {
    expect(lastSeenFor("room_a", () => 1000)).toBeNull();
    expect(lastSeenFor("room_a", () => 2000)).toBeNull(); // same page load: stable
    resetLastSeen();
    expect(lastSeenFor("room_a", () => 3000)).toBe(1000);
  });
});
