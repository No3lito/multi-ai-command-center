"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api as defaultApi, isApiError, type Api } from "./api";
import type { Message } from "./types";

export interface PendingMessage {
  /** Client idempotency key; also the pending item's identity. Reused on retry. */
  key: string;
  text: string;
  /** Principal ids mentioned in the text; reused on retry. */
  mentions: string[];
  status: "sending" | "failed";
  error?: string;
  createdAt: string;
}

export function newIdempotencyKey(): string {
  return crypto.randomUUID();
}

/**
 * Optimistic send queue for one room. Each message gets a crypto.randomUUID()
 * idempotency key; retrying a failed message reuses the same key so the server
 * returns the original instead of creating a duplicate. When the server message
 * arrives it is handed to `onDelivered` (which dedupes by id) and the pending
 * entry is removed.
 */
export function useOutbox(
  roomId: string | null,
  onDelivered: (message: Message) => void,
  client: Pick<Api, "postMessage"> = defaultApi,
) {
  const [pending, setPending] = useState<PendingMessage[]>([]);
  const roomRef = useRef(roomId);
  const deliveredRef = useRef(onDelivered);
  const clientRef = useRef(client);
  const inFlight = useRef(new Set<string>());

  useEffect(() => {
    deliveredRef.current = onDelivered;
    clientRef.current = client;
  });

  useEffect(() => {
    roomRef.current = roomId;
    inFlight.current.clear();
    // Pending items belong to one room.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setPending([]);
  }, [roomId]);

  const dispatch = useCallback(async (key: string, text: string, mentions: string[]) => {
    const room = roomRef.current;
    if (!room || inFlight.current.has(key)) return;
    inFlight.current.add(key);
    setPending((prev) => prev.map((p) => (p.key === key ? { ...p, status: "sending", error: undefined } : p)));
    try {
      const message = await clientRef.current.postMessage(room, text, key, mentions);
      if (roomRef.current !== room) return;
      deliveredRef.current(message);
      setPending((prev) => prev.filter((p) => p.key !== key));
    } catch (e) {
      if (roomRef.current !== room) return;
      const error = isApiError(e) ? e.message : "Message could not be sent.";
      setPending((prev) => prev.map((p) => (p.key === key ? { ...p, status: "failed", error } : p)));
    } finally {
      inFlight.current.delete(key);
    }
  }, []);

  const send = useCallback(
    (text: string, mentions: readonly string[] = []) => {
      const key = newIdempotencyKey();
      const ids = [...mentions];
      setPending((prev) => [
        ...prev,
        { key, text, mentions: ids, status: "sending", createdAt: new Date().toISOString() },
      ]);
      void dispatch(key, text, ids);
      return key;
    },
    [dispatch],
  );

  const retry = useCallback(
    (key: string) => {
      const item = pending.find((p) => p.key === key);
      if (item) void dispatch(item.key, item.text, item.mentions);
    },
    [pending, dispatch],
  );

  const discard = useCallback((key: string) => {
    setPending((prev) => prev.filter((p) => p.key !== key));
  }, []);

  return { pending, send, retry, discard };
}
