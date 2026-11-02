import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { RunsPanel } from "@/components/RunsPanel";
import { ROOM_A, msg } from "@/test/fakeWebSocket";
import { RUN_ID, agentMsg, coordMsg, run } from "@/test/fixtures";
import type { Message, Run } from "./types";
import { useRuns } from "./useRuns";

function makeClient(initial: Run[]) {
  let list = initial;
  const getRunImpl = vi.fn(async (id: string): Promise<Run> => {
    const found = list.find((r) => r.id === id);
    if (!found) throw new Error("missing");
    return found;
  });
  return {
    set(next: Run[]) {
      list = next;
    },
    client: {
      listRuns: vi.fn(async () => list),
      getRun: getRunImpl,
      cancelRun: vi.fn(async (id: string) => ({ ...list.find((r) => r.id === id)!, status: "cancelled" as const })),
    },
  };
}

function Harness({
  messages,
  ready,
  client,
}: {
  messages: Message[];
  ready: boolean;
  client: ReturnType<typeof makeClient>["client"];
}) {
  const runs = useRuns(ROOM_A, messages, ready, { client, pollMs: 10_000 });
  return (
    <RunsPanel
      hasRoom
      runs={runs.runs}
      loaded={runs.loaded}
      error={runs.error}
      agentName={() => null}
      onCancel={runs.cancel}
      onRetry={runs.reload}
    />
  );
}

async function flush() {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0);
  });
}

describe("useRuns", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("renders status, step, turns and spent of budget with 4 decimals for small amounts", async () => {
    const { client } = makeClient([run({ turn_count: 2, spent_usd: 0.0123, step: "critique" })]);
    render(<Harness messages={[]} ready client={client} />);
    await flush();
    expect(screen.getByTestId("run-status")).toHaveTextContent("Running");
    expect(screen.getByTestId("run-turns")).toHaveTextContent("2/8");
    expect(screen.getByTestId("run-step")).toHaveTextContent("critique");
    expect(screen.getByTestId("run-spent")).toHaveTextContent("$0.0123 of $0.50");
    expect(screen.getByTestId("run-simulated")).toBeInTheDocument();
    expect(screen.getByTestId("run-cancel")).toBeInTheDocument();
  });

  it("refreshes a run when a message with its correlation_id arrives, not for history", async () => {
    const c = makeClient([run()]);
    const history = [agentMsg(1)];
    const { rerender } = render(<Harness messages={history} ready client={c.client} />);
    await flush();
    expect(c.client.getRun).not.toHaveBeenCalled();

    c.set([run({ status: "completed", step: "done", turn_count: 3, updated_at: "2026-11-02T12:05:00Z" })]);
    rerender(<Harness messages={[...history, coordMsg(2, "task.result", "Done")]} ready client={c.client} />);
    await flush();
    expect(c.client.getRun).toHaveBeenCalledWith(RUN_ID);
    expect(screen.getByTestId("run-status")).toHaveTextContent("Completed");
    expect(screen.queryByTestId("run-cancel")).toBeNull();
  });

  it("ignores messages without a run correlation", async () => {
    const c = makeClient([run()]);
    const { rerender } = render(<Harness messages={[]} ready client={c.client} />);
    await flush();
    const listCalls = c.client.listRuns.mock.calls.length;
    rerender(<Harness messages={[msg(1)]} ready client={c.client} />);
    await flush();
    expect(c.client.getRun).not.toHaveBeenCalled();
    expect(c.client.listRuns.mock.calls.length).toBe(listCalls);
  });

  it("reloads the list when an unknown run id appears", async () => {
    const c = makeClient([]);
    const { rerender } = render(<Harness messages={[]} ready client={c.client} />);
    await flush();
    expect(screen.getByText("No runs yet.")).toBeInTheDocument();
    expect(c.client.listRuns).toHaveBeenCalledTimes(1);

    c.set([run({ kind: "reply", agent_id: "agt_x", planner_id: null, critic_id: null })]);
    rerender(<Harness messages={[coordMsg(1, "task.assign", "Go")]} ready client={c.client} />);
    await flush();
    expect(c.client.listRuns).toHaveBeenCalledTimes(2);
    expect(screen.getAllByTestId("run-item")).toHaveLength(1);
  });

  it("polls every 10 s while a run is active and stops once all are finished", async () => {
    const c = makeClient([run()]);
    render(<Harness messages={[]} ready client={c.client} />);
    await flush();
    expect(c.client.listRuns).toHaveBeenCalledTimes(1);
    c.set([run({ status: "completed", step: "done", updated_at: "2026-11-02T12:01:00Z" })]);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });
    expect(c.client.listRuns).toHaveBeenCalledTimes(2);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(30_000);
    });
    expect(c.client.listRuns).toHaveBeenCalledTimes(2);
  });

  it("cancels a run", async () => {
    const c = makeClient([run()]);
    render(<Harness messages={[]} ready client={c.client} />);
    await flush();
    await act(async () => {
      screen.getByTestId("run-cancel").click();
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(c.client.cancelRun).toHaveBeenCalledWith(RUN_ID);
    expect(screen.getByTestId("run-status")).toHaveTextContent("Cancelled");
  });
});
