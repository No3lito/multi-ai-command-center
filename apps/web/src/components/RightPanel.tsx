import type { SocketStatus } from "@/lib/roomSocket";
import type { RoomDetail } from "@/lib/types";
import { connectionLabel } from "./ConnectionPill";
import { KindBadge } from "./MessageList";

interface Props {
  open: boolean;
  detail: RoomDetail | null;
  status: SocketStatus;
  lastSeq: number;
  hasRoom: boolean;
}

export function RightPanel({ open, detail, status, lastSeq, hasRoom }: Props) {
  return (
    <aside
      id="right-sidebar"
      aria-label="Room details"
      className={`fixed inset-y-0 right-0 z-40 flex w-72 shrink-0 flex-col overflow-y-auto border-l border-line bg-panel transition-transform xl:static xl:translate-x-0 ${
        open ? "translate-x-0" : "invisible translate-x-full xl:visible"
      }`}
    >
      <div className="flex h-12 shrink-0 items-center border-b border-line px-3">
        <h2 className="text-sm font-semibold">Room details</h2>
      </div>

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

      <Placeholder title="Agents" />
      <Placeholder title="Tasks" />
      <Placeholder title="Usage and cost" />
    </aside>
  );
}

function Section({ title, count, children }: { title: string; count?: number; children: React.ReactNode }) {
  return (
    <section className="border-b border-line px-3 py-3">
      <h3 className="mb-2 flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wider text-muted">
        {title}
        {count !== undefined && <span className="rounded bg-panel-2 px-1 font-mono">{count}</span>}
      </h3>
      {children}
    </section>
  );
}

function Placeholder({ title }: { title: string }) {
  return (
    <section className="border-b border-line px-3 py-2.5">
      <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted">{title}</h3>
      <p className="mt-0.5 text-xs text-muted">Arrives in Milestone B</p>
    </section>
  );
}
