import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { run } from "@/test/fixtures";
import { HistoryPanel } from "./HistoryPanel";

describe("HistoryPanel", () => {
  it("searches, shows briefs, and archives or unarchives runs", async () => {
    const user = userEvent.setup();
    const done = run({
      id: "run_a",
      status: "completed",
      brief: "**Bottom line:** No edge at 5 s.",
      finished_at: "2026-11-03T08:00:00Z",
    });
    const client = {
      history: vi.fn().mockResolvedValue({ runs: [done], decisions: [] }),
      archiveRun: vi.fn().mockResolvedValue({ ...done, archived_at: "2026-11-03T09:00:00Z" }),
      unarchiveRun: vi.fn(),
    };
    const onRunChanged = vi.fn();
    render(<HistoryPanel roomId="room_x" client={client} onRunChanged={onRunChanged} debounceMs={0} />);
    expect(await screen.findByText("No edge at 5 s.")).toBeInTheDocument();
    await user.click(screen.getByText("No edge at 5 s."));
    expect(screen.getByTestId("history-brief")).toHaveTextContent("Bottom line");

    await user.type(screen.getByTestId("history-search"), "H123");
    await waitFor(() =>
      expect(client.history).toHaveBeenLastCalledWith("room_x", "H123", "include", expect.anything()),
    );
    await user.click(screen.getByTestId("history-archived"));
    await waitFor(() => expect(client.history).toHaveBeenLastCalledWith("room_x", "H123", "only", expect.anything()));

    await user.click(screen.getByTestId("history-archive-toggle"));
    expect(client.archiveRun).toHaveBeenCalledWith("run_a");
    expect(onRunChanged).toHaveBeenCalledWith(expect.objectContaining({ archived_at: "2026-11-03T09:00:00Z" }));
  });
});
