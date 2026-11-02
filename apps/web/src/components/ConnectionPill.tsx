import type { SocketStatus } from "@/lib/roomSocket";

const LABEL: Record<SocketStatus, string> = {
  connecting: "Connecting",
  live: "Live",
  reconnecting: "Reconnecting",
  offline: "Offline",
};

const STYLE: Record<SocketStatus, string> = {
  connecting: "bg-warn-soft text-warn",
  live: "bg-ok-soft text-ok",
  reconnecting: "bg-warn-soft text-warn",
  offline: "bg-danger-soft text-danger",
};

export function connectionLabel(status: SocketStatus): string {
  return LABEL[status];
}

export function ConnectionPill({ status }: { status: SocketStatus }) {
  return (
    <span
      data-testid="connection-status"
      data-status={status}
      role="status"
      className={`inline-flex shrink-0 items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium ${STYLE[status]}`}
    >
      <span
        aria-hidden="true"
        className={`h-1.5 w-1.5 rounded-full bg-current ${status === "live" ? "" : "animate-pulse"}`}
      />
      {LABEL[status]}
    </span>
  );
}
