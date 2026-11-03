"use client";

import { useEffect, useMemo, useState } from "react";
import { assignSpeakerStyles, type SenderStyle, type Speaker } from "./senderStyle";

/** Allocate during calculation; commit the registry after rendering. */
export function useSpeakerStyles(senders: readonly Speaker[]) {
  const [registry, setRegistry] = useState<ReadonlyMap<string, SenderStyle>>(() => new Map());
  const styles = useMemo(() => {
    const hasHuman = senders.some((sender) => sender.kind === "owner" || sender.kind === "human");
    return assignSpeakerStyles(
      hasHuman
        ? senders
        : [...senders, { id: "pending-owner", kind: "owner", display_name: "You" }],
      registry,
    );
  }, [senders, registry]);

  useEffect(() => {
    if (styles.size === registry.size) return;
    // Persist newly discovered identities without setting state during render.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setRegistry(styles);
  }, [styles, registry]);

  return styles;
}
