import { roomSocketUrl } from "./api";
import { isMessage } from "./messageStore";
import type { Message } from "./types";

/**
 * Framework-free WebSocket client for one room, implementing the Milestone A
 * reconnect rule: track the highest seq (per room), reconnect on close or after
 * 30 s without any frame, exponential backoff 1 s doubling to 30 s with jitter,
 * resume with after_seq=<highest seq>.
 */

export const BACKOFF_BASE_MS = 1_000;
export const BACKOFF_MAX_MS = 30_000;
export const IDLE_TIMEOUT_MS = 30_000;

/** Close codes after which reconnecting cannot help. */
export const FATAL_CLOSE_CODES = {
  4401: "unauthenticated",
  4403: "origin_not_allowed",
  4404: "room_not_found",
} as const;
export type FatalCloseCode = keyof typeof FATAL_CLOSE_CODES;

export type SocketStatus = "connecting" | "live" | "reconnecting" | "offline";

/** The subset of the browser WebSocket used here, so tests can supply a fake. */
export interface WebSocketLike {
  readonly readyState: number;
  onopen: ((ev: unknown) => void) | null;
  onmessage: ((ev: { data: unknown }) => void) | null;
  onclose: ((ev: { code: number; reason: string }) => void) | null;
  onerror: ((ev: unknown) => void) | null;
  send(data: string): void;
  close(code?: number, reason?: string): void;
}

export type SocketFactory = (url: string) => WebSocketLike;

const OPEN = 1;

export const defaultSocketFactory: SocketFactory = (url) => new WebSocket(url) as unknown as WebSocketLike;

/**
 * Delay before reconnect attempt `attempt` (0-based): 1 s, 2 s, 4 s ... capped
 * at 30 s, then jittered down by up to 25% so clients do not reconnect in lockstep.
 * `random` returning 1 yields the un-jittered value.
 */
export function backoffDelay(attempt: number, random: () => number = Math.random): number {
  const base = Math.min(BACKOFF_MAX_MS, BACKOFF_BASE_MS * 2 ** Math.max(0, attempt));
  const r = Math.min(1, Math.max(0, random()));
  return Math.round(base * (0.75 + 0.25 * r));
}

export interface RoomSocketOptions {
  roomId: string;
  /** Highest contiguous seq received for this room; used as after_seq on every (re)connect. */
  getAfterSeq: () => number;
  onMessage: (message: Message) => void;
  onReady: (lastSeq: number) => void;
  onStatus: (status: SocketStatus) => void;
  onFatal: (code: FatalCloseCode) => void;
  createSocket?: SocketFactory;
  wsBaseUrl?: string;
  random?: () => number;
}

export class RoomSocket {
  private readonly opts: RoomSocketOptions;
  private ws: WebSocketLike | null = null;
  private attempt = 0;
  private everReady = false;
  private stopped = false;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private idleTimer: ReturnType<typeof setTimeout> | null = null;

  constructor(opts: RoomSocketOptions) {
    this.opts = opts;
  }

  start(): void {
    this.stopped = false;
    this.connect();
  }

  stop(): void {
    this.stopped = true;
    this.clearTimers();
    this.dropSocket(1000, "client closed");
  }

  /** Reconnect immediately (for example when the browser comes back online), resetting backoff. */
  reconnectNow(): void {
    if (this.stopped) return;
    this.clearTimers();
    this.dropSocket(4000, "client reconnect");
    this.attempt = 0;
    this.connect();
  }

  /** Drop the current socket and reconnect through the normal backoff path. */
  resync(): void {
    if (this.stopped) return;
    this.clearTimers();
    this.dropSocket(4000, "client resync");
    this.scheduleReconnect();
  }

  private connect(): void {
    if (this.stopped) return;
    this.opts.onStatus(this.everReady || this.attempt > 0 ? "reconnecting" : "connecting");
    const url = roomSocketUrl(this.opts.roomId, this.opts.getAfterSeq(), this.opts.wsBaseUrl);
    let ws: WebSocketLike;
    try {
      ws = (this.opts.createSocket ?? defaultSocketFactory)(url);
    } catch {
      this.scheduleReconnect();
      return;
    }
    this.ws = ws;
    this.armIdleTimer();

    ws.onopen = () => {
      if (ws === this.ws) this.armIdleTimer();
    };
    ws.onmessage = (ev) => {
      if (ws !== this.ws) return;
      this.armIdleTimer();
      this.handleFrame(ws, ev.data);
    };
    ws.onerror = () => {
      // A close event always follows; reconnect is handled there.
    };
    ws.onclose = (ev) => {
      if (ws !== this.ws) return;
      this.ws = null;
      this.clearIdleTimer();
      if (this.stopped) return;
      if (ev.code in FATAL_CLOSE_CODES) {
        this.opts.onStatus("offline");
        this.opts.onFatal(ev.code as FatalCloseCode);
        return;
      }
      this.scheduleReconnect();
    };
  }

  private handleFrame(ws: WebSocketLike, data: unknown): void {
    if (typeof data !== "string") return;
    let frame: unknown;
    try {
      frame = JSON.parse(data);
    } catch {
      return;
    }
    if (!frame || typeof frame !== "object") return;
    const f = frame as { type?: unknown; message?: unknown; last_seq?: unknown };
    switch (f.type) {
      case "message":
        if (isMessage(f.message) && f.message.room_id === this.opts.roomId) this.opts.onMessage(f.message);
        return;
      case "ready":
        this.attempt = 0;
        this.everReady = true;
        this.opts.onStatus("live");
        this.opts.onReady(typeof f.last_seq === "number" ? f.last_seq : this.opts.getAfterSeq());
        return;
      case "ping":
        if (ws.readyState === OPEN) {
          try {
            ws.send(JSON.stringify({ type: "pong" }));
          } catch {
            // Ignore; the close handler will reconnect if the socket is dead.
          }
        }
        return;
      default:
        return;
    }
  }

  private scheduleReconnect(): void {
    if (this.stopped) return;
    this.opts.onStatus("reconnecting");
    const delay = backoffDelay(this.attempt, this.opts.random);
    this.attempt += 1;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, delay);
  }

  private armIdleTimer(): void {
    this.clearIdleTimer();
    this.idleTimer = setTimeout(() => {
      this.idleTimer = null;
      // 30 s without any frame (including the 15 s ping): treat as dead.
      this.dropSocket(4000, "idle timeout");
      this.scheduleReconnect();
    }, IDLE_TIMEOUT_MS);
  }

  private clearIdleTimer(): void {
    if (this.idleTimer !== null) {
      clearTimeout(this.idleTimer);
      this.idleTimer = null;
    }
  }

  private clearTimers(): void {
    this.clearIdleTimer();
    if (this.reconnectTimer !== null) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }

  private dropSocket(code: number, reason: string): void {
    const ws = this.ws;
    this.ws = null;
    if (!ws) return;
    ws.onopen = null;
    ws.onmessage = null;
    ws.onerror = null;
    ws.onclose = null;
    try {
      ws.close(code, reason);
    } catch {
      // Already closed.
    }
  }
}
