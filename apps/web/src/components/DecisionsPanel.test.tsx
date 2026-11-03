import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { Decision } from "@/lib/types";
import { run } from "@/test/fixtures";
import { DecisionsPanel, bottomLine, describePlan } from "./DecisionsPanel";

function decision(over: Partial<Decision> = {}): Decision {
  return {
    id: `dec_${"a".repeat(32)}`,
    room_id: "room_x",
    run_id: `run_${"1".repeat(32)}`,
    run_goal: "Review",
    question: "Approve the capped Helius coverage audit?",
    recommendation: "Approve: it decides whether H123 can be tested.",
    cost: "about 50k Helius credits",
    on_approve: { workflow: "review", worker: "Grok Bot", goal: "Run the audit." },
    on_more_info: { workflow: "collab", worker: null, goal: "" },
    status: "pending",
    owner_note: null,
    decided_at: null,
    follow_up_run_id: null,
    created_at: "2026-11-02T12:00:00Z",
    ...over,
  };
}

const BRIEF = `**Bottom line:** No edge at a 5-second delay; three clean retests are justified.
**Decided:**
- H123, H14, H52 are the retest candidates.
**Waiting on you:**
- Approve the launch coverage check (Helius credits).
**Next steps:**
1. Grok Bot runs the check after approval.`;

describe("bottomLine", () => {
  it("takes the text after the Bottom line heading", () =>
    expect(bottomLine(BRIEF)).toBe("No edge at a 5-second delay; three clean retests are justified."));
  it("handles a heading on its own line", () =>
    expect(bottomLine("## Bottom line\nShip the fix.\n## Decided\n- x")).toBe("Ship the fix."));
});

describe("DecisionsPanel", () => {
  it("renders nothing until a run has a brief", () => {
    const { container } = render(<DecisionsPanel runs={[run({ brief: null })]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows the latest conclusion and what is waiting on the owner", () => {
    const latest = run({
      id: `run_${"2".repeat(32)}`,
      brief: BRIEF,
      pending_decisions: ["Approve the launch coverage check (Helius credits)."],
      goal: "Evaluate Grok Bot's research log\nwith details",
    });
    const older = run({ brief: "**Bottom line:** Earlier result.", pending_decisions: [] });
    render(<DecisionsPanel runs={[latest, older]} />);
    expect(screen.getByTestId("decision-latest")).toHaveTextContent("No edge at a 5-second delay");
    expect(screen.getByTestId("decision-latest")).toHaveTextContent("Evaluate Grok Bot's research log");
    expect(screen.getAllByTestId("decision-item").map((li) => li.textContent)).toEqual([
      "Approve the launch coverage check (Helius credits).",
    ]);
    expect(screen.getByTestId("decision-waiting")).toHaveTextContent("(1)");
    expect(screen.queryByTestId("decision-brief")).not.toBeInTheDocument(); // past briefs live in History
  });

  it("says plainly when nothing is waiting", () => {
    render(<DecisionsPanel runs={[run({ brief: "**Bottom line:** Done.", pending_decisions: [] })]} />);
    expect(screen.getByTestId("decision-waiting")).toHaveTextContent("Nothing. No decision is needed");
  });
});

describe("describePlan", () => {
  it("names the worker for review and build", () =>
    expect(describePlan({ workflow: "review", worker: "Grok Bot", goal: "" })).toBe(
      "Grok Bot does the work, then Claude and GPT check it.",
    ));
  it("says nothing more runs for none", () =>
    expect(describePlan({ workflow: "none", worker: null, goal: "" })).toMatch(/^Nothing more runs/));
});

describe("decision cards", () => {
  const briefed = run({ brief: "**Bottom line:** Retest H123.", pending_decisions: ["old bullet"] });

  it("shows a card per pending decision instead of the bullet list", () => {
    render(<DecisionsPanel runs={[briefed]} decisions={[decision()]} onAnswer={vi.fn()} />);
    const card = screen.getByTestId("decision-card");
    expect(card).toHaveTextContent("Approve the capped Helius coverage audit?");
    expect(screen.getByTestId("decision-recommendation")).toHaveTextContent("Recommended: Approve");
    expect(screen.getByTestId("decision-cost")).toHaveTextContent("about 50k Helius credits");
    expect(screen.getByTestId("decision-plan")).toHaveTextContent("If approved: Grok Bot does the work");
    expect(screen.queryByTestId("decision-item")).not.toBeInTheDocument();
  });

  it("approves with a note and budget in one click", async () => {
    const user = userEvent.setup();
    const onAnswer = vi.fn().mockResolvedValue({});
    render(<DecisionsPanel runs={[briefed]} decisions={[decision()]} onAnswer={onAnswer} />);
    await user.click(screen.getByTestId("decision-add-note"));
    await user.type(screen.getByTestId("decision-note"), "cap 50k credits");
    await user.type(screen.getByTestId("decision-budget"), "0.4");
    await user.click(screen.getByTestId("decision-approve"));
    expect(onAnswer).toHaveBeenCalledWith(`dec_${"a".repeat(32)}`, {
      answer: "approve",
      note: "cap 50k credits",
      budget_usd: 0.4,
    });
  });

  it("declines without sending a budget, and blocks a bad budget", async () => {
    const user = userEvent.setup();
    const onAnswer = vi.fn().mockResolvedValue({});
    render(<DecisionsPanel runs={[briefed]} decisions={[decision()]} onAnswer={onAnswer} />);
    await user.click(screen.getByTestId("decision-add-note"));
    await user.type(screen.getByTestId("decision-budget"), "9");
    expect(screen.getByTestId("decision-approve")).toBeDisabled();
    await user.click(screen.getByTestId("decision-decline"));
    expect(onAnswer).toHaveBeenCalledWith(`dec_${"a".repeat(32)}`, { answer: "decline" });
  });

  it("shows the server's error on the card", async () => {
    const user = userEvent.setup();
    const onAnswer = vi
      .fn()
      .mockRejectedValue({ status: 409, code: "x", message: "This decision was already approved" });
    render(<DecisionsPanel runs={[briefed]} decisions={[decision()]} onAnswer={onAnswer} />);
    await user.click(screen.getByTestId("decision-more-info"));
    expect(await screen.findByText(/already approved|Could not save/)).toBeInTheDocument();
  });

  it("lists recently decided items with notes and follow-ups", () => {
    const done = decision({
      id: `dec_${"b".repeat(32)}`,
      status: "approved",
      owner_note: "cap 50k",
      follow_up_run_id: `run_${"9".repeat(32)}`,
    });
    render(<DecisionsPanel runs={[briefed]} decisions={[done]} onAnswer={vi.fn()} />);
    expect(screen.getByTestId("decision-waiting")).toHaveTextContent("Nothing. No decision is needed");
    const item = screen.getByTestId("decision-decided-item");
    expect(item).toHaveTextContent("Approved");
    expect(item).toHaveTextContent("Note: cap 50k");
    expect(item).toHaveTextContent("Follow-up run started");
  });
});

describe("self-explaining cards", () => {
  const briefed = run({ brief: "**Bottom line:** Retest H123." });
  const explained = decision({
    recommended: "more_info",
    why: "The audit decides whether the retests can run at all.",
    suggested_note: "Run the zero-credit replay test first.",
  });

  it("explains itself and fills in the agents' note", () => {
    render(<DecisionsPanel runs={[briefed]} decisions={[explained]} onAnswer={vi.fn()} />);
    expect(screen.getByTestId("decision-why")).toHaveTextContent("Why it matters: The audit decides");
    expect(screen.getByTestId("decision-note")).toHaveValue("Run the zero-credit replay test first.");
    expect(screen.getByTestId("decision-follow")).toHaveTextContent(
      "Do what they recommend: Need more info (with the note)",
    );
  });

  it("follows the recommendation with the (edited) note in one click", async () => {
    const user = userEvent.setup();
    const onAnswer = vi.fn().mockResolvedValue({});
    render(<DecisionsPanel runs={[briefed]} decisions={[explained]} onAnswer={onAnswer} />);
    await user.type(screen.getByTestId("decision-note"), " Cap 25k.");
    await user.click(screen.getByTestId("decision-follow"));
    expect(onAnswer).toHaveBeenCalledWith(explained.id, {
      answer: "more_info",
      note: "Run the zero-credit replay test first. Cap 25k.",
    });
  });

  it("has no follow button when the agents gave no clear recommendation", () => {
    render(<DecisionsPanel runs={[briefed]} decisions={[decision({ recommended: null })]} onAnswer={vi.fn()} />);
    expect(screen.queryByTestId("decision-follow")).not.toBeInTheDocument();
  });
});
