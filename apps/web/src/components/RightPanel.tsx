import type { ReactNode } from "react";
import type { SocketStatus } from "@/lib/roomSocket";
import type { RoomDetail } from "@/lib/types";
import { connectionLabel } from "./ConnectionPill";
import { KindBadge } from "./MessageList";
import { PanelSection as Section } from "./PanelSection";

interface Props {
  open: boolean;
  detail: RoomDetail | null;
  status: SocketStatus;
  lastSeq: number;
  hasRoom: boolean;
  /** Milestone B panels (agents, collaborate, runs, usage), rendered above members. */
  children?: ReactNode;
}

export function RightPanel({ open, detail, status, lastSeq, hasRoom, children }: Props) {
  return (
    <aside
      id="right-sidebar"
      aria-label="Room details"
      className={`fixed inset-y-0 right-0 z-40 flex w-80 shrink-0 flex-col overflow-y-auto border-l border-line bg-panel transition-transform xl:static xl:translate-x-0 ${
        open ? "translate-x-0" : "invisible translate-x-full xl:visible"
      }`}
    >
      <div className="flex h-12 shrink-0 items-center border-b border-line px-3">
        <h2 className="text-sm font-semibold">Room details</h2>
      </div>

      {children}

      <Section title="Members" count={detail?.members.length}>
        {!hasRoom || !detail ? (
          <p className="text-muted">{hasRoom ? "Loading..." : "No room selected."}</p>
        ) : (
          <ul className="space-y-1">
            {detail.members.map((m) => (
              <li key={m.id} className="flex items-center gap-2">
                <span className="min-w-0 flex-1 truncate">{m.display_name}</span>
                <KindBadge kind={m.kind} />
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section title="Connection">
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 font-mono text-xs">
          <dt className="text-muted">status</dt>
          <dd>{hasRoom ? connectionLabel(status) : "n/a"}</dd>
          <dt className="text-muted">last seq</dt>
          <dd>{hasRoom ? lastSeq : "n/a"}</dd>
          <dt className="text-muted">room</dt>
          <dd className="truncate" title={detail?.id}>
            {detail?.id ?? "n/a"}
          </dd>
        </dl>
      </Section>
    </aside>
  );
}
