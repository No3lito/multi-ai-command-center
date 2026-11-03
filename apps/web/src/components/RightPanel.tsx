"use client";

import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
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
  /** Tabs and panels, rendered above members. */
  children?: ReactNode;
  /** Show the members and connection sections (the Setup tab). */
  showDetails?: boolean;
}

const WIDTH_KEY = "room-details-width";
const MIN_WIDTH = 280;
const DESKTOP_WIDTH = 1280;

function clampWidth(width: number, viewport: number) {
  return Math.min(Math.max(MIN_WIDTH, width), Math.floor(viewport * 0.6));
}

export function RightPanel({ open, detail, status, lastSeq, hasRoom, children, showDetails = true }: Props) {
  const [preferredWidth, setPreferredWidth] = useState(320);
  const [viewport, setViewport] = useState(0);
  const drag = useRef<{ pointerId: number; x: number; width: number } | null>(null);
  const desktop = viewport >= DESKTOP_WIDTH;
  const width = desktop ? clampWidth(preferredWidth, viewport) : 320;

  useEffect(() => {
    let savedWidth = 320;
    try {
      const saved = window.localStorage.getItem(WIDTH_KEY);
      if (saved !== null && saved.trim() !== "" && Number.isFinite(Number(saved))) {
        savedWidth = Number(saved);
      }
    } catch {
      // Storage may be disabled; resizing still works for this session.
    }
    // Read browser-only state after hydration.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setPreferredWidth(savedWidth);
    const onResize = () => {
      drag.current = null;
      setViewport(window.innerWidth);
    };
    onResize();
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  const resize = (next: number) => {
    if (window.innerWidth < DESKTOP_WIDTH) return;
    const bounded = clampWidth(next, window.innerWidth);
    setPreferredWidth(bounded);
    try {
      window.localStorage.setItem(WIDTH_KEY, String(bounded));
    } catch {
      // A blocked or full store must not prevent resizing.
    }
  };

  return (
    <aside
      id="right-sidebar"
      aria-label="Room details"
      style={{ "--room-details-width": `${width}px` } as CSSProperties}
      className={`fixed inset-y-0 right-0 z-40 flex w-80 shrink-0 flex-col overflow-hidden border-l border-line bg-panel transition-transform xl:relative xl:w-[var(--room-details-width)] xl:translate-x-0 ${
        open ? "translate-x-0" : "invisible translate-x-full xl:visible"
      }`}
    >
      {desktop && (
        <div
          role="separator"
          aria-label="Resize room details"
          aria-controls="right-sidebar"
          aria-orientation="vertical"
          aria-valuemin={MIN_WIDTH}
          aria-valuemax={Math.floor(viewport * 0.6)}
          aria-valuenow={width}
          aria-valuetext={`${width} pixels`}
          tabIndex={0}
          className="group absolute inset-y-0 left-0 z-10 hidden w-2 touch-none cursor-col-resize select-none outline-none xl:block"
          onPointerDown={(event) => {
            if (event.button !== 0 || window.innerWidth < DESKTOP_WIDTH) return;
            event.preventDefault();
            event.currentTarget.focus();
            event.currentTarget.setPointerCapture(event.pointerId);
            drag.current = { pointerId: event.pointerId, x: event.clientX, width };
          }}
          onPointerMove={(event) => {
            const start = drag.current;
            if (!start || start.pointerId !== event.pointerId) return;
            resize(start.width + start.x - event.clientX);
          }}
          onPointerUp={() => { drag.current = null; }}
          onPointerCancel={() => { drag.current = null; }}
          onLostPointerCapture={() => { drag.current = null; }}
          onKeyDown={(event) => {
            if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
            event.preventDefault();
            resize(width + (event.key === "ArrowLeft" ? 10 : -10));
          }}
        >
          <span className="absolute inset-y-0 left-0 w-0.5 bg-transparent group-hover:bg-accent group-focus-visible:bg-accent group-active:bg-accent" />
        </div>
      )}
      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
      <div className="flex h-12 shrink-0 items-center border-b border-line px-3">
        <h2 className="text-sm font-semibold">Room details</h2>
      </div>

      {children}

      {showDetails && (
        <>
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
        </>
      )}
      </div>
    </aside>
  );
}
