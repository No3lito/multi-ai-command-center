import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { BACKOFF_MAX_MS, IDLE_TIMEOUT_MS, RoomSocket, backoffDelay, type SocketStatus } from "./roomSocket";
import { FakeWebSocket, ROOM_A, factory, msg } from "@/test/fakeWebSocket";

function setup(afterSeq = { v: 0 }) {
  const events = {
    messages: [] as number[],
    ready: [] as number[],
    status: [] as SocketStatus[],
    fatal: [] as number[],
  };
  const socket = new RoomSocket({
    roomId: ROOM_A,
    getAfterSeq: () => afterSeq.v,
    onMessage: (m) => {
      events.messages.push(m.seq);
      afterSeq.v = Math.max(afterSeq.v, m.seq);
    },
    onReady: (s) => events.ready.push(s),
    onStatus: (s) => events.status.push(s),
    onFatal: (c) => events.fatal.push(c),
    createSocket: factory,
    wsBaseUrl: "ws://test",
    random: () => 1, // no jitter, deterministic
  });
  return { socket, events, afterSeq };
}

describe("backoffDelay", () => {
  it("doubles from 1 s and caps at 30 s", () => {
    const delays = Array.from({ length: 8 }, (_, i) => backoffDelay(i, () => 1));
    expect(delays).toEqual([1000, 2000, 4000, 8000, 16000, 30000, 30000, 30000]);
  });

  it("applies jitter within 75% to 100% of the base and never exceeds the cap", () => {
    expect(backoffDelay(0, () => 0)).toBe(750);
    for (let i = 0; i < 50; i++) {
      const d = backoffDelay(10, Math.random);
      expect(d).toBeGreaterThanOrEqual(BACKOFF_MAX_MS * 0.75);
      expect(d).toBeLessThanOrEqual(BACKOFF_MAX_MS);
    }
  });
});

describe("RoomSocket", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    FakeWebSocket.reset();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("connects with after_seq, handles replay then ready, and goes live", () => {
    const { socket, events } = setup({ v: 3 });
    socket.start();
    const ws = FakeWebSocket.latest();
    expect(ws.url).toBe(`ws://test/api/ws/rooms/${ROOM_A}?after_seq=3`);
    ws.open();
    ws.message(msg(4));
    ws.message(msg(5));
    expect(events.status.at(-1)).toBe("connecting");
    ws.ready(5);
    expect(events.messages).toEqual([4, 5]);
    expect(events.ready).toEqual([5]);
    expect(events.status.at(-1)).toBe("live");
    socket.stop();
  });

  it("replies pong to ping", () => {
    const { socket } = setup();
    socket.start();
    const ws = FakeWebSocket.latest();
    ws.open();
    ws.frame({ type: "ping", ts: "2026-11-02T12:00:00Z" });
    expect(ws.sent.map((s) => JSON.parse(s))).toEqual([{ type: "pong" }]);
    socket.stop();
  });

  it("ignores messages for other rooms and malformed frames", () => {
    const { socket, events } = setup();
    socket.start();
    const ws = FakeWebSocket.latest();
    ws.message(msg(1, `room_${"c".repeat(32)}`));
    ws.onmessage?.({ data: "not json" });
    ws.frame({ type: "message", message: { nope: true } });
    expect(events.messages).toEqual([]);
    socket.stop();
  });

  it("reconnects with exponential backoff capped at 30 s, using the highest seq", () => {
    const { socket, afterSeq } = setup();
    socket.start();
    const first = FakeWebSocket.latest();
    first.open();
    first.message(msg(1));
    first.message(msg(2));
    first.ready(2);

    const expected = [1000, 2000, 4000, 8000, 16000, 30000, 30000];
    for (const delay of expected) {
      const before = FakeWebSocket.instances.length;
      FakeWebSocket.latest().serverClose(1006);
      vi.advanceTimersByTime(delay - 1);
      expect(FakeWebSocket.instances.length).toBe(before);
      vi.advanceTimersByTime(1);
      expect(FakeWebSocket.instances.length).toBe(before + 1);
      expect(FakeWebSocket.latest().afterSeq).toBe(2);
    }
    expect(afterSeq.v).toBe(2);
    socket.stop();
  });

  it("resets backoff after a successful ready", () => {
    const { socket } = setup();
    socket.start();
    FakeWebSocket.latest().serverClose(1006);
    vi.advanceTimersByTime(1000);
    FakeWebSocket.latest().serverClose(1006);
    vi.advanceTimersByTime(2000);
    const ws = FakeWebSocket.latest();
    ws.ready(0);
    ws.serverClose(1006);
    const before = FakeWebSocket.instances.length;
    vi.advanceTimersByTime(1000);
    expect(FakeWebSocket.instances.length).toBe(before + 1);
    socket.stop();
  });

  it("reconnects after 30 s with no frame, and any frame resets the idle timer", () => {
    const { socket, events } = setup();
    socket.start();
    const ws = FakeWebSocket.latest();
    ws.open();
    ws.ready(0);
    vi.advanceTimersByTime(IDLE_TIMEOUT_MS - 1000);
    ws.frame({ type: "ping", ts: "x" });
    vi.advanceTimersByTime(IDLE_TIMEOUT_MS - 1000);
    expect(ws.closedWith).toBeNull();
    vi.advanceTimersByTime(1000);
    expect(ws.closedWith).not.toBeNull();
    expect(events.status.at(-1)).toBe("reconnecting");
    vi.advanceTimersByTime(1000);
    expect(FakeWebSocket.instances.length).toBe(2);
    socket.stop();
  });

  it("stops on fatal close codes", () => {
    const { socket, events } = setup();
    socket.start();
    FakeWebSocket.latest().serverClose(4404);
    vi.advanceTimersByTime(60_000);
    expect(FakeWebSocket.instances.length).toBe(1);
    expect(events.fatal).toEqual([4404]);
    expect(events.status.at(-1)).toBe("offline");
  });

  it("stop() closes the socket and prevents reconnects", () => {
    const { socket } = setup();
    socket.start();
    const ws = FakeWebSocket.latest();
    socket.stop();
    expect(ws.closedWith?.code).toBe(1000);
    vi.advanceTimersByTime(120_000);
    expect(FakeWebSocket.instances.length).toBe(1);
  });
});
