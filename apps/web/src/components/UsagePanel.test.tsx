import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { usage } from "@/test/fixtures";
import { UsagePanel } from "./UsagePanel";

describe("UsagePanel", () => {
  it("renders spent of cap, remaining, reserved and the per-model table", () => {
    render(<UsagePanel usage={usage()} error={null} />);
    expect(screen.getByTestId("usage-spent")).toHaveTextContent("$0.42");
    expect(screen.getByTestId("usage-cap")).toHaveTextContent("$10.00");
    expect(screen.getByTestId("usage-remaining")).toHaveTextContent("$9.57");
    expect(screen.getByTestId("usage-reserved")).toHaveTextContent("$0.01");
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "4");
    const row = screen.getByTestId("usage-row");
    expect(row).toHaveTextContent("claude-sonnet-5-5");
    expect(row).toHaveTextContent("3");
    expect(row).toHaveTextContent("2,100");
    expect(row).toHaveTextContent("$0.0114");
  });

  it("keeps simulated usage separate from real usage and spend", () => {
    render(
      <UsagePanel
        usage={usage({
          spent_usd: 0,
          remaining_usd: 10,
          reserved_usd: 0,
          by_provider: [
            {
              provider: "simulated",
              model: "sim-claude",
              calls: 3,
              input_tokens: 300,
              output_tokens: 200,
              cost_usd: 0,
              simulated: true,
            },
          ],
          simulated_calls: 3,
        })}
        error={null}
      />,
    );
    expect(screen.getByTestId("usage-spent")).toHaveTextContent("$0.00");
    expect(screen.queryByTestId("usage-table")).toBeNull();
    expect(screen.getByText("No real API calls yet.")).toBeInTheDocument();
    const sim = screen.getByTestId("usage-simulated");
    expect(within(sim).getByTestId("usage-simulated-calls")).toHaveTextContent("3");
    expect(sim).toHaveTextContent(/not real API usage/i);
    expect(sim).toHaveTextContent("sim-claude");
  });

  it("shows an error when usage cannot load", () => {
    render(<UsagePanel usage={null} error="Nope" />);
    expect(screen.getByRole("alert")).toHaveTextContent("Nope");
  });
});
