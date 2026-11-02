"use client";

import { useEffect, useRef } from "react";
import type { Message } from "./types";

/**
 * Calls `onNew` with messages that arrive after `ready` first becomes true.
 * History already loaded at that moment is not reported. Tracking is by id, so
 * a message that fills a seq gap later is still reported exactly once.
 */
export function useNewMessages(messages: readonly Message[], ready: boolean, onNew: (fresh: Message[]) => void) {
  const seenRef = useRef<Set<string> | null>(null);
  const cbRef = useRef(onNew);

  useEffect(() => {
    cbRef.current = onNew;
  });

  useEffect(() => {
    if (!ready) return;
    if (seenRef.current === null) {
      seenRef.current = new Set(messages.map((m) => m.id));
      return;
    }
    const seen = seenRef.current;
    const fresh = messages.filter((m) => !seen.has(m.id));
    if (fresh.length === 0) return;
    for (const m of fresh) seen.add(m.id);
    cbRef.current(fresh);
  }, [messages, ready]);
}
