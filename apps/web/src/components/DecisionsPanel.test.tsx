import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { Decision } from "@/lib/types";
import { run } from "@/test/fixtures";
import { DecisionsPanel, bottomLine, confirmLabel, describePlan, whatHappens } from "./DecisionsPanel";

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
  it("skips the verdict line and markdown symbols when there is no Bottom line heading", () =>
    expect(bottomLine("**Verdict:** Needs you.\n**Ship** the **fix** today.")).toBe("Ship the fix today."));
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
    const { unmount } = render(<DecisionsPanel runs={[latest, older]} />);
    // Look A1: while something waits on the owner, it comes first and the conclusion steps aside.
    expect(screen.queryByTestId("decision-latest")).toBeNull();
    expect(screen.getAllByTestId("decision-item").map((li) => li.textContent)).toEqual([
      "Approve the launch coverage check (Helius credits).",
    ]);
    unmount();
    render(<DecisionsPanel runs={[{ ...latest, pending_decisions: [] }, older]} />);
    expect(screen.getByTestId("decision-latest")).toHaveTextContent("No edge at a 5-second delay");
    expect(screen.getByTestId("decision-latest")).toHaveTextContent("Evaluate Grok Bot's research log");
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

  it("approves with a note and budget after a confirm step", async () => {
    const user = userEvent.setup();
    const onAnswer = vi.fn().mockResolvedValue({});
    render(<DecisionsPanel runs={[briefed]} decisions={[decision()]} onAnswer={onAnswer} />);
    await user.click(screen.getByTestId("decision-add-note"));
    await user.type(screen.getByTestId("decision-note"), "cap 50k credits");
    await user.type(screen.getByTestId("decision-budget"), "0.4");
    await user.click(screen.getByTestId("decision-approve"));
    await user.click(screen.getByTestId("decision-confirm"));
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
    await user.click(screen.getByTestId("decision-confirm"));
    expect(onAnswer).toHaveBeenCalledWith(`dec_${"a".repeat(32)}`, { answer: "decline" });
  });

  it("shows the server's error on the card", async () => {
    const user = userEvent.setup();
    const onAnswer = vi
      .fn()
      .mockRejectedValue({ status: 409, code: "x", message: "This decision was already approved" });
    render(<DecisionsPanel runs={[briefed]} decisions={[decision()]} onAnswer={onAnswer} />);
    await user.click(screen.getByTestId("decision-more-info"));
    await user.click(screen.getByTestId("decision-confirm"));
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

  it("follows the recommendation with the (edited) note after a confirm step", async () => {
    const user = userEvent.setup();
    const onAnswer = vi.fn().mockResolvedValue({});
    render(<DecisionsPanel runs={[briefed]} decisions={[explained]} onAnswer={onAnswer} />);
    await user.type(screen.getByTestId("decision-note"), " Cap 25k.");
    await user.click(screen.getByTestId("decision-follow"));
    await user.click(screen.getByTestId("decision-confirm"));
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

describe("confirm before answering", () => {
  it("says what will happen and its budget before anything is sent, and Back cancels", async () => {
    const user = userEvent.setup();
    const onAnswer = vi.fn().mockResolvedValue({});
    render(
      <DecisionsPanel runs={[run({ brief: "**Bottom line:** x" })]} decisions={[decision()]} onAnswer={onAnswer} />,
    );
    await user.click(screen.getByTestId("decision-add-note"));
    await user.type(screen.getByTestId("decision-budget"), "0.4");
    await user.click(screen.getByTestId("decision-approve"));
    expect(onAnswer).not.toHaveBeenCalled();
    expect(screen.getByTestId("decision-what-happens")).toHaveTextContent("Starts Grok Bot does the work");
    expect(screen.getByTestId("decision-what-happens")).toHaveTextContent("Budget: $0.40");
    expect(screen.getByTestId("decision-confirm")).toHaveTextContent("Approve and start · $0.40");
    await user.click(screen.getByTestId("decision-confirm-back"));
    expect(screen.queryByTestId("decision-confirm-box")).not.toBeInTheDocument();
    await user.click(screen.getByTestId("decision-decline"));
    expect(screen.getByTestId("decision-confirm")).toHaveTextContent("Record answer");
    await user.dblClick(screen.getByTestId("decision-confirm"));
    expect(onAnswer).toHaveBeenCalledTimes(1);
  });

  it("is honest when approving would start nothing", () => {
    const blocked = decision({ cannot_run_reason: "Nobody connected can do this." });
    expect(whatHappens(blocked, "approve", undefined)).toBe("Nothing starts: Nobody connected can do this.");
    expect(confirmLabel(blocked, "approve", undefined)).toBe("Record answer");
    expect(confirmLabel(decision(), "more_info", undefined)).toBe("Ask and start");
  });
});

describe("code job cards", () => {
  const pr = decision({
    question: "Merge pull request #7 into main?",
    on_approve: { workflow: "none", worker: null, goal: "" },
    on_more_info: { workflow: "code", worker: null, goal: "Fix add()" },
    code_pr: { number: 7, url: "https://github.com/o/r/pull/7", title: "[Claude + GPT] Fix add()" },
  });

  it("says plainly that approve merges, decline closes and more info sends it back", () => {
    expect(whatHappens(pr, "approve", undefined)).toMatch(/^Merges pull request #7 into main/);
    expect(whatHappens(pr, "decline", undefined)).toMatch(/^Closes pull request #7/);
    expect(whatHappens(pr, "more_info", undefined)).toMatch(/^Sends pull request #7 back/);
    expect(confirmLabel(pr, "approve", undefined)).toBe("Merge #7");
    expect(confirmLabel(pr, "decline", undefined)).toBe("Close #7");
    expect(confirmLabel(pr, "more_info", undefined)).toBe("Send it back");
  });

  it("links to the pull request", () => {
    render(<DecisionsPanel runs={[]} decisions={[pr]} onAnswer={vi.fn()} />);
    const link = screen.getByTestId("decision-pr-link");
    expect(link).toHaveAttribute("href", "https://github.com/o/r/pull/7");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("describes a proposed code change and its budget", () => {
    const proposal = decision({ on_approve: { workflow: "code", worker: null, goal: "Add a dark mode toggle" } });
    expect(describePlan(proposal.on_approve)).toMatch(/one of Claude and GPT writes the change/);
    expect(whatHappens(proposal, "approve", undefined)).toMatch(/the code job limit/);
  });
});

describe("ready-made choices", () => {
  const withOptions = decision({
    question: "Run the backtest on the 37 tokens?",
    options: [
      { label: "Yes, all 37", detail: "About $0.40", answer: "approve", note: "Paper only." },
      { label: "Top 10 only", detail: "About $0.15", answer: "approve", note: "Top 10 only, under $0.20." },
      { label: "Not now", detail: "Nothing runs", answer: "decline", note: "" },
    ],
  });

  it("sends the picked option's answer and note, after the confirm step", async () => {
    const user = userEvent.setup();
    const onAnswer = vi.fn(async () => undefined);
    render(<DecisionsPanel runs={[]} decisions={[withOptions]} onAnswer={onAnswer} />);
    const choices = screen.getAllByTestId("decision-option");
    expect(choices).toHaveLength(3);
    expect(choices[0]).toHaveAttribute("aria-checked", "true");
    expect(screen.queryByTestId("decision-approve")).toBeNull(); // the old buttons wait behind "Write my own"
    await user.click(choices[1]!);
    await user.click(screen.getByTestId("decision-send-option"));
    expect(screen.getByTestId("decision-confirm-box")).toHaveTextContent("Your answer: Top 10 only");
    await user.click(screen.getByTestId("decision-confirm"));
    expect(onAnswer).toHaveBeenCalledWith(withOptions.id, { answer: "approve", note: "Top 10 only, under $0.20." });
  });

  it("can still write a note by hand", async () => {
    const user = userEvent.setup();
    render(<DecisionsPanel runs={[]} decisions={[withOptions]} onAnswer={vi.fn()} />);
    await user.click(screen.getByTestId("decision-write-own"));
    expect(screen.queryByTestId("decision-options")).toBeNull();
    expect(screen.getByTestId("decision-approve")).toBeInTheDocument();
  });

  it("shows the usual buttons when the agents prepared no options", () => {
    render(<DecisionsPanel runs={[]} decisions={[decision()]} onAnswer={vi.fn()} />);
    expect(screen.queryByTestId("decision-options")).toBeNull();
    expect(screen.getByTestId("decision-approve")).toBeInTheDocument();
  });
});
