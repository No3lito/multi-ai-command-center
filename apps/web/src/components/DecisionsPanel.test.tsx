import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { run } from "@/test/fixtures";
import { DecisionsPanel, bottomLine } from "./DecisionsPanel";

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

  it("shows the latest conclusion, what is waiting on the owner, and the full brief on demand", async () => {
    const user = userEvent.setup();
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
    expect(screen.getAllByTestId("decision-brief")).toHaveLength(2);
    expect(screen.queryByTestId("decision-brief-full")).not.toBeInTheDocument();
    await user.click(screen.getByText("Earlier result."));
    expect(screen.getByTestId("decision-brief-full")).toHaveTextContent("Earlier result.");
  });

  it("says plainly when nothing is waiting", () => {
    render(<DecisionsPanel runs={[run({ brief: "**Bottom line:** Done.", pending_decisions: [] })]} />);
    expect(screen.getByTestId("decision-waiting")).toHaveTextContent("Nothing. No decision is needed");
  });
});
