import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FakeWebSocket, ROOM_A, ROOM_B, factory, msg } from "@/test/fakeWebSocket";
import type { MessagePage } from "./types";
import { useRoomStream } from "./useRoomStream";

function pageApi(pages: Record<string, MessagePage[]>) {
  const calls: Array<{ room: string; after: number }> = [];
  const counters: Record<string, number> = {};
  return {
    calls,
    api: {
      listMessages: vi.fn(async (room: string, after: number) => {
        calls.push({ room, after });
        const i = counters[room] ?? 0;
        counters[room] = i + 1;
        return pages[room]?.[i] ?? { items: [], has_more: false, next_after_seq: after };
      }),
    },
  };
}

const opts = (api: ReturnType<typeof pageApi>["api"]) => ({
  api,
  createSocket: factory,
  wsBaseUrl: "ws://test",
  random: () => 1,
});

async function flush() {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0);
  });
}

describe("useRoomStream", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    FakeWebSocket.reset();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("paginates history with has_more, then opens the socket after the highest loaded seq", async () => {
    const { api, calls } = pageApi({
      [ROOM_A]: [
        { items: [msg(1), msg(2)], has_more: true, next_after_seq: 2 },
        { items: [msg(3)], has_more: false, next_after_seq: 3 },
      ],
    });
    const { result, unmount } = renderHook(() => useRoomStream(ROOM_A, opts(api)));
    await flush();
    expect(calls).toEqual([
      { room: ROOM_A, after: 0 },
      { room: ROOM_A, after: 2 },
    ]);
    expect(result.current.messages.map((m) => m.seq)).toEqual([1, 2, 3]);
    expect(FakeWebSocket.instances).toHaveLength(1);
    expect(FakeWebSocket.latest().afterSeq).toBe(3);
    unmount();
  });

  it("handles replay then ready, dedupes by id and keeps seq order", async () => {
    const { api } = pageApi({ [ROOM_A]: [{ items: [msg(1)], has_more: false, next_after_seq: 1 }] });
    const { result, unmount } = renderHook(() => useRoomStream(ROOM_A, opts(api)));
    await flush();
    const ws = FakeWebSocket.latest();
    act(() => {
      ws.open();
      ws.message(msg(1)); // duplicate of HTTP history
      ws.message(msg(2));
      ws.ready(2);
    });
    expect(result.current.status).toBe("live");
    expect(result.current.lastSeq).toBe(2);

    // A POST response can arrive before the socket delivers earlier messages.
    act(() => result.current.ingest(msg(4)));
    expect(result.current.messages.map((m) => m.seq)).toEqual([1, 2, 4]);
    expect(result.current.lastSeq).toBe(2);
    expect(ws.closedWith).toBeNull(); // POST gaps do not force a resync

    act(() => {
      ws.message(msg(3));
      ws.message(msg(4)); // same message again, now on the socket
    });
    expect(result.current.messages.map((m) => m.seq)).toEqual([1, 2, 3, 4]);
    expect(result.current.lastSeq).toBe(4);
    unmount();
  });

  it("reconnects with after_seq equal to the highest seq received", async () => {
    const { api } = pageApi({ [ROOM_A]: [{ items: [msg(1)], has_more: false, next_after_seq: 1 }] });
    const { result, unmount } = renderHook(() => useRoomStream(ROOM_A, opts(api)));
    await flush();
    act(() => {
      const ws = FakeWebSocket.latest();
      ws.ready(1);
      ws.message(msg(2));
      ws.message(msg(3));
      ws.serverClose(1006);
    });
    expect(result.current.status).toBe("reconnecting");
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(FakeWebSocket.instances).toHaveLength(2);
    expect(FakeWebSocket.latest().afterSeq).toBe(3);
    unmount();
  });

  it("resyncs from the last contiguous seq when the socket skips a seq", async () => {
    const { api } = pageApi({ [ROOM_A]: [{ items: [msg(1)], has_more: false, next_after_seq: 1 }] });
    const { result, unmount } = renderHook(() => useRoomStream(ROOM_A, opts(api)));
    await flush();
    const first = FakeWebSocket.latest();
    act(() => {
      first.ready(1);
      first.message(msg(3)); // seq 2 missing
    });
    expect(result.current.lastSeq).toBe(1);
    expect(first.closedWith).not.toBeNull();
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    const second = FakeWebSocket.latest();
    expect(second).not.toBe(first);
    expect(second.afterSeq).toBe(1);
    act(() => {
      second.message(msg(2));
      second.message(msg(3));
      second.ready(3);
    });
    expect(result.current.messages.map((m) => m.seq)).toEqual([1, 2, 3]);
    expect(result.current.lastSeq).toBe(3);
    unmount();
  });

  it("resets per-room seq and closes the old socket when switching rooms", async () => {
    const { api, calls } = pageApi({
      [ROOM_A]: [{ items: [msg(1), msg(2), msg(3)], has_more: false, next_after_seq: 3 }],
      [ROOM_B]: [{ items: [msg(1, ROOM_B)], has_more: false, next_after_seq: 1 }],
    });
    const { result, rerender, unmount } = renderHook(({ id }) => useRoomStream(id, opts(api)), {
      initialProps: { id: ROOM_A },
    });
    await flush();
    const wsA = FakeWebSocket.latest();
    expect(wsA.afterSeq).toBe(3);

    rerender({ id: ROOM_B });
    await flush();
    expect(wsA.closedWith?.code).toBe(1000);
    expect(calls.at(-1)).toEqual({ room: ROOM_B, after: 0 });
    const wsB = FakeWebSocket.latest();
    expect(wsB.url).toContain(ROOM_B);
    expect(wsB.afterSeq).toBe(1);
    expect(result.current.messages.map((m) => m.room_id)).toEqual([ROOM_B]);

    // A late frame from the old socket is ignored.
    act(() => wsA.message(msg(4)));
    expect(result.current.messages).toHaveLength(1);
    unmount();
  });

  it("reports a load error when history cannot be fetched", async () => {
    const api = { listMessages: vi.fn(async () => Promise.reject(new Error("down"))) };
    const { result, unmount } = renderHook(() => useRoomStream(ROOM_A, opts(api)));
    await flush();
    expect(result.current.phase).toBe("error");
    expect(FakeWebSocket.instances).toHaveLength(0);
    unmount();
  });
});
