"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api as defaultApi, isApiError, type Api } from "./api";
import { mergeMessages } from "./messageStore";
import { RoomSocket, type FatalCloseCode, type SocketFactory, type SocketStatus } from "./roomSocket";
import type { Message } from "./types";

export type LoadPhase = "loading" | "ready" | "error";
export type StreamError = { code: string; message: string };

export interface RoomStreamState {
  messages: Message[];
  phase: LoadPhase;
  status: SocketStatus;
  /** Highest contiguous seq received for this room (seq is per room and gap-free). */
  lastSeq: number;
  error: StreamError | null;
  fatal: FatalCloseCode | null;
}

export interface UseRoomStreamOptions {
  api?: Pick<Api, "listMessages">;
  createSocket?: SocketFactory;
  wsBaseUrl?: string;
  random?: () => number;
  pageSize?: number;
}

const FATAL_MESSAGES: Record<FatalCloseCode, StreamError> = {
  4401: { code: "unauthenticated", message: "Your session ended. Sign in again." },
  4403: { code: "origin_not_allowed", message: "The server rejected this page's origin for live updates." },
  4404: { code: "room_not_found", message: "This room no longer exists." },
};

const INITIAL: RoomStreamState = {
  messages: [],
  phase: "loading",
  status: "connecting",
  lastSeq: 0,
  error: null,
  fatal: null,
};

/**
 * Loads a room's history (GET, paginated with has_more) and then streams new
 * messages over the room WebSocket, resuming from the highest seq loaded.
 * All seq tracking is per room and resets when `roomId` changes; switching
 * rooms closes the previous socket.
 */
export function useRoomStream(roomId: string | null, options: UseRoomStreamOptions = {}) {
  const [state, setState] = useState<RoomStreamState>(INITIAL);
  const [reloadToken, setReloadToken] = useState(0);
  const highestSeqRef = useRef(0);
  const socketRef = useRef<RoomSocket | null>(null);
  const optsRef = useRef(options);

  useEffect(() => {
    optsRef.current = options;
  });

  const messagesRef = useRef<Message[]>([]);

  /**
   * Add messages from any source (GET page, socket, POST response).
   * Dedupes by id, keeps seq order and advances the highest *contiguous* seq.
   * Since seq is gap-free within a room, a gap on the socket means something
   * was missed, so the socket resyncs from the last contiguous seq.
   */
  const applyMessages = useCallback((incoming: Message[], forRoom: string, source: "http" | "socket" | "post") => {
    const relevant = incoming.filter((m) => m.room_id === forRoom);
    if (relevant.length === 0) return;
    const messages = mergeMessages(messagesRef.current, relevant);
    const { highest, gap } = advanceContiguous(messages, highestSeqRef.current);
    if (messages === messagesRef.current && highest === highestSeqRef.current) return;
    messagesRef.current = messages;
    highestSeqRef.current = highest;
    setState((prev) => ({ ...prev, messages, lastSeq: highest }));
    if (gap && source === "socket") socketRef.current?.resync();
  }, []);

  /** Server says everything up to lastSeq has been sent: trust it, so a server-side gap cannot loop. */
  const acknowledgeReady = useCallback((lastSeq: number) => {
    const base = Math.max(highestSeqRef.current, lastSeq);
    const { highest } = advanceContiguous(messagesRef.current, base);
    highestSeqRef.current = highest;
    setState((prev) => ({ ...prev, phase: "ready", error: null, lastSeq: highest }));
  }, []);

  useEffect(() => {
    if (!roomId) return;
    const opts = optsRef.current;
    const client = opts.api ?? defaultApi;
    const pageSize = opts.pageSize ?? 200;
    const abort = new AbortController();
    let cancelled = false;

    highestSeqRef.current = 0;
    messagesRef.current = [];
    // Reset per-room state when the room changes (seq is per room).
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setState(INITIAL);

    const socket = new RoomSocket({
      roomId,
      getAfterSeq: () => highestSeqRef.current,
      onMessage: (m) => {
        if (!cancelled) applyMessages([m], roomId, "socket");
      },
      onReady: (lastSeq) => {
        if (!cancelled) acknowledgeReady(lastSeq);
      },
      onStatus: (status) => {
        if (!cancelled) setState((prev) => (prev.status === status ? prev : { ...prev, status }));
      },
      onFatal: (code) => {
        if (!cancelled) setState((prev) => ({ ...prev, fatal: code, error: FATAL_MESSAGES[code] }));
      },
      createSocket: opts.createSocket,
      wsBaseUrl: opts.wsBaseUrl,
      random: opts.random,
    });

    (async () => {
      try {
        let after = 0;
        for (;;) {
          const page = await client.listMessages(roomId, after, pageSize, abort.signal);
          if (cancelled) return;
          applyMessages(page.items, roomId, "http");
          const pageMax = page.items.reduce((max, m) => Math.max(max, m.seq), after);
          const next = Math.max(page.next_after_seq ?? 0, pageMax);
          if (!page.has_more || next <= after) break;
          after = next;
        }
        if (cancelled) return;
        setState((prev) => ({ ...prev, phase: "ready" }));
        socketRef.current = socket;
        socket.start();
      } catch (e) {
        if (cancelled) return;
        const err: StreamError = isApiError(e)
          ? { code: e.code, message: e.message }
          : { code: "unknown", message: "Could not load messages." };
        setState((prev) => ({ ...prev, phase: "error", status: "offline", error: err }));
      }
    })();

    const onOnline = () => socket.reconnectNow();
    window.addEventListener("online", onOnline);

    return () => {
      cancelled = true;
      abort.abort();
      window.removeEventListener("online", onOnline);
      socket.stop();
      if (socketRef.current === socket) socketRef.current = null;
    };
  }, [roomId, reloadToken, applyMessages, acknowledgeReady]);

  /** Feed a message from a POST response; deduped by id. */
  const ingest = useCallback(
    (message: Message) => {
      if (roomId) applyMessages([message], roomId, "post");
    },
    [roomId, applyMessages],
  );

  const reload = useCallback(() => setReloadToken((t) => t + 1), []);

  return { ...state, ingest, reload };
}

/** Walk sorted messages from `start`, advancing through consecutive seq values. */
export function advanceContiguous(sorted: readonly Message[], start: number): { highest: number; gap: boolean } {
  let highest = start;
  for (const m of sorted) {
    if (m.seq <= highest) continue;
    if (m.seq === highest + 1) highest = m.seq;
    else return { highest, gap: true };
  }
  return { highest, gap: false };
}
