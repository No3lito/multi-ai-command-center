"use client";

import { useEffect, useMemo } from "react";
import { assignSpeakerStyles, pendingSpeaker, type SenderStyle, type Speaker } from "./senderStyle";

/** Calculate from metadata; persist allocations after commit without another render. */
export function useSpeakerStyles(senders: readonly Speaker[], hasPending = false) {
  const registry = useMemo(() => new Map<string, SenderStyle>(), []);
  const effectiveSenders = hasPending ? [...senders, pendingSpeaker(senders)] : senders;
  // Serialize only allocation metadata so fresh caller arrays do not invalidate the memo.
  const signature = JSON.stringify(effectiveSenders.map((sender) => ({
    id: sender.principal_id ?? sender.id ?? sender.display_name,
    kind: sender.kind,
    display_name: sender.display_name,
  })));
  const styles = useMemo(
    () => assignSpeakerStyles(JSON.parse(signature) as Speaker[], registry),
    [signature, registry],
  );

  useEffect(() => {
    for (const [id, style] of styles) registry.set(id, style);
  }, [styles, registry]);

  return styles;
}
