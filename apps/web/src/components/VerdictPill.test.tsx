import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { Decision } from "@/lib/types";
import { run } from "@/test/fixtures";
import { DecisionsPanel } from "./DecisionsPanel";
import { RunsPanel } from "./RunsPanel";
import { VerdictPill } from "./VerdictPill";

describe("verdicts and wrap-up", () => {
  it("labels each verdict in words, and shows nothing before a brief", () => {
    const { rerender, container } = render(<VerdictPill verdict="needs_you" />);
    expect(screen.getByTestId("verdict")).toHaveTextContent("Needs you");
    rerender(<VerdictPill verdict="blocked" />);
    expect(screen.getByTestId("verdict")).toHaveTextContent("Blocked");
    rerender(<VerdictPill verdict={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("offers Wrap it up on active plan runs only", async () => {
    const user = userEvent.setup();
    const onWrapUp = vi.fn().mockResolvedValue(undefined);
    const props = {
      hasRoom: true,
      loaded: true,
      error: null,
      agentName: () => "Claude",
      onCancel: vi.fn(),
      onRetry: vi.fn(),
    };
    render(
      <RunsPanel
        {...props}
        onWrapUp={onWrapUp}
        runs={[
          run({ id: "run_a", status: "running" }),
          run({ id: "run_b", status: "completed", verdict: "done" }),
          run({ id: "run_c", status: "running", kind: "reply" }),
        ]}
      />,
    );
    const buttons = screen.getAllByTestId("run-wrap-up");
    expect(buttons).toHaveLength(1);
    await user.click(buttons[0]!);
    expect(onWrapUp).toHaveBeenCalledWith("run_a");
    expect(screen.getByTestId("verdict")).toHaveTextContent("Done");
  });

  it("says plainly when approving would start nothing, and marks the final round", () => {
    const d = {
      id: "dec_1",
      room_id: "room_x",
      run_id: "run_1",
      run_goal: "g",
      question: "Build the new dashboard?",
      recommendation: "Approve",
      recommended: "approve",
      cost: null,
      on_approve: { workflow: "build", worker: "Grok", goal: "" },
      on_more_info: { workflow: "none", worker: null, goal: "" },
      status: "pending",
      owner_note: null,
      decided_at: null,
      follow_up_run_id: null,
      created_at: "2026-11-03T12:00:00Z",
      cannot_run_reason: "Nobody connected can do this: Grok is not available in this room.",
      final_round: true,
    } as Decision;
    render(
      <DecisionsPanel
        runs={[run({ brief: "**Bottom line:** x", verdict: "needs_you" })]}
        decisions={[d]}
        onAnswer={vi.fn()}
      />,
    );
    expect(screen.getByTestId("decision-cannot-run")).toHaveTextContent(
      "If approved: nothing starts. Nobody connected",
    );
    expect(screen.queryByTestId("decision-plan")).not.toBeInTheDocument();
    expect(screen.getByTestId("decision-final-round")).toHaveTextContent("Final round");
    expect(screen.getByTestId("decision-latest")).toHaveTextContent("Needs you");
  });
});
