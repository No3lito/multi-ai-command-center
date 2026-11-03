import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { Message, Run } from "@/lib/types";
import { RUN_ID, agentMsg, coordMsg, run } from "@/test/fixtures";
import { MessageList } from "./MessageList";

const convo: Message[] = [
  { ...coordMsg(1, "task.assign", "Claude: write a plan"), correlation_id: RUN_ID },
  { ...agentMsg(2), correlation_id: RUN_ID },
  { ...coordMsg(3, "task.result", "Run complete"), correlation_id: RUN_ID },
];

function renderList(runs: Run[], onArchive = vi.fn().mockResolvedValue({})) {
  const props = { messages: convo, pending: [], loading: false, onRetry: () => {}, onDiscard: () => {}, onArchive };
  const view = render(<MessageList {...props} runs={runs} />);
  return { ...view, rerender: (next: Run[]) => view.rerender(<MessageList {...props} runs={next} />), onArchive };
}

describe("folded runs in the chat", () => {
  it("folds a finished run into one card with its bottom line; the conversation opens on demand", async () => {
    const user = userEvent.setup();
    const { onArchive } = renderList([
      run({ status: "completed", brief: "**Bottom line:** Ship it.", spent_usd: 0.18 }),
    ]);
    const card = screen.getByTestId("run-fold");
    expect(card).toHaveTextContent("Create a basic login interface");
    expect(screen.getByTestId("run-fold-line")).toHaveTextContent("Ship it.");
    expect(screen.queryByTestId("message-item")).not.toBeInTheDocument();
    await user.click(screen.getByTestId("run-fold-toggle"));
    expect(screen.getAllByTestId("message-item").length).toBeGreaterThan(0);
    await user.click(screen.getByTestId("run-fold-archive"));
    expect(onArchive).toHaveBeenCalledWith(RUN_ID);
  });

  it("keeps a run the owner watched in progress open after it finishes", () => {
    const { rerender } = renderList([run({ status: "running" })]);
    expect(screen.queryByTestId("run-fold")).not.toBeInTheDocument();
    rerender([run({ status: "completed", brief: "**Bottom line:** Done." })]);
    expect(screen.getByTestId("run-fold")).toHaveAttribute("data-open", "true");
    expect(screen.getAllByTestId("message-item").length).toBeGreaterThan(0);
  });
});
