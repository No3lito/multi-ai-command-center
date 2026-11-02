import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { msg } from "@/test/fakeWebSocket";
import { agentMsg, usage } from "@/test/fixtures";
import type { Message } from "./types";
import { useUsage } from "./useUsage";

describe("useUsage", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("loads, refreshes after agent messages (not human ones) and every 30 s", async () => {
    const client = { getUsage: vi.fn(async () => usage()) };
    const { result, rerender } = renderHook(
      ({ messages }: { messages: Message[] }) => useUsage(messages, true, { client, debounceMs: 100 }),
      { initialProps: { messages: [] as Message[] } },
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(result.current.usage?.cap_usd).toBe(10);
    expect(client.getUsage).toHaveBeenCalledTimes(1);

    rerender({ messages: [msg(1)] });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(200);
    });
    expect(client.getUsage).toHaveBeenCalledTimes(1);

    rerender({ messages: [msg(1), agentMsg(2)] });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(200);
    });
    expect(client.getUsage).toHaveBeenCalledTimes(2);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(30_000);
    });
    expect(client.getUsage).toHaveBeenCalledTimes(3);
  });
});
