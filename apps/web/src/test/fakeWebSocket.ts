import type { WebSocketLike } from "@/lib/roomSocket";
import type { Message } from "@/lib/types";

/** In-memory WebSocket double. Records every instance and every frame sent. */
export class FakeWebSocket implements WebSocketLike {
  static instances: FakeWebSocket[] = [];

  static reset(): void {
    FakeWebSocket.instances = [];
  }

  static latest(): FakeWebSocket {
    const ws = FakeWebSocket.instances[FakeWebSocket.instances.length - 1];
    if (!ws) throw new Error("no FakeWebSocket created");
    return ws;
  }

  readonly url: string;
  readyState = 0;
  sent: string[] = [];
  closedWith: { code?: number; reason?: string } | null = null;
  onopen: ((ev: unknown) => void) | null = null;
  onmessage: ((ev: { data: unknown }) => void) | null = null;
  onclose: ((ev: { code: number; reason: string }) => void) | null = null;
  onerror: ((ev: unknown) => void) | null = null;

  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }

  get afterSeq(): number {
    return Number(new URL(this.url).searchParams.get("after_seq"));
  }

  send(data: string): void {
    this.sent.push(data);
  }

  close(code?: number, reason?: string): void {
    this.closedWith = { code, reason };
    this.readyState = 3;
  }

  // Server-side helpers.
  open(): void {
    this.readyState = 1;
    this.onopen?.({});
  }

  frame(obj: unknown): void {
    this.onmessage?.({ data: JSON.stringify(obj) });
  }

  message(m: Message): void {
    this.frame({ type: "message", message: m });
  }

  ready(lastSeq: number): void {
    this.frame({ type: "ready", last_seq: lastSeq });
  }

  serverClose(code = 1006, reason = ""): void {
    this.readyState = 3;
    this.onclose?.({ code, reason });
  }
}

export const factory = (url: string) => new FakeWebSocket(url);

export const ROOM_A = `room_${"a".repeat(32)}`;
export const ROOM_B = `room_${"b".repeat(32)}`;

export function msg(seq: number, room = ROOM_A, text = `message ${seq}`): Message {
  return {
    id: `msg_${room.slice(5, 6)}${seq.toString(16).padStart(31, "0")}`,
    protocol: "ccmp/1",
    seq,
    room_id: room,
    thread_id: null,
    sender: { principal_id: `usr_${"1".repeat(32)}`, kind: "owner", display_name: "Noel" },
    kind: "chat",
    reply_to: null,
    mentions: [],
    body: { text },
    task_id: null,
    correlation_id: null,
    usage: null,
    created_at: "2026-11-02T12:00:00Z",
  };
}
