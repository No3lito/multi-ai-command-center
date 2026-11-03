"use client";

import { useMemo } from "react";
import { assignSpeakerStyles, pendingSpeaker, type Speaker } from "./senderStyle";

/** Speaker colors for the senders on screen. Fixed identities (owner, Claude, GPT, Coordinator)
 * always get their own color; others get the next free one in a stable order. Calculated from
 * the senders alone, so render stays pure (no registry mutated after render). */
export function useSpeakerStyles(senders: readonly Speaker[], hasPending = false) {
  const effectiveSenders = hasPending ? [...senders, pendingSpeaker(senders)] : senders;
  // Serialize only allocation metadata so fresh caller arrays do not invalidate the memo.
  const signature = JSON.stringify(
    effectiveSenders.map((sender) => ({
      id: sender.principal_id ?? sender.id ?? sender.display_name,
      kind: sender.kind,
      display_name: sender.display_name,
    })),
  );
  return useMemo(() => assignSpeakerStyles(JSON.parse(signature) as Speaker[]), [signature]);
}
