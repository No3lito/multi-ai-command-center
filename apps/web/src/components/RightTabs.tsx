"use client";

import { useEffect, useRef, type ReactNode } from "react";

export type TabId = "decide" | "runs" | "history" | "setup";

const TABS: { id: TabId; label: string }[] = [
  { id: "decide", label: "Decide" },
  { id: "runs", label: "Runs" },
  { id: "history", label: "History" },
  { id: "setup", label: "Setup" },
];

/** Tab bar for the right panel: what needs the owner first, setup last. */
export function RightTabs({
  tab,
  onChange,
  badges = {},
}: {
  tab: TabId;
  onChange: (tab: TabId) => void;
  badges?: Partial<Record<TabId, number>>;
}) {
  return (
    <div role="tablist" aria-label="Room panels" className="flex shrink-0 border-b border-line px-1">
      {TABS.map((t) => {
        const n = badges[t.id] ?? 0;
        return (
          <button
            key={t.id}
            type="button"
            role="tab"
            id={`tab-${t.id}`}
            data-testid={`tab-${t.id}`}
            aria-selected={tab === t.id}
            aria-controls={`tabpanel-${t.id}`}
            onClick={() => onChange(t.id)}
            className={`flex-1 border-b-2 px-1 py-2 text-xs font-medium ${
              tab === t.id ? "border-accent text-fg" : "border-transparent text-muted hover:text-fg"
            }`}
          >
            {t.label}
            {n > 0 && <span className="ml-1 rounded-full bg-warn-soft px-1.5 text-[10px] text-warn">{n}</span>}
          </button>
        );
      })}
    </div>
  );
}

/** A simple modal: closes on Escape or the backdrop, and returns focus where it was. */
export function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  const panelRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const before = document.activeElement as HTMLElement | null;
    panelRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      before?.focus?.();
    };
  }, [onClose]);
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/50 p-4 sm:p-10">
      <button type="button" aria-label="Close" className="fixed inset-0 cursor-default" onClick={onClose} />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        data-testid="modal"
        className="relative w-full max-w-md rounded-lg border border-line bg-panel shadow-xl outline-none"
      >
        <div className="flex items-center border-b border-line px-3 py-2">
          <h2 className="flex-1 text-sm font-semibold">{title}</h2>
          <button
            type="button"
            data-testid="modal-close"
            onClick={onClose}
            className="rounded px-2 py-0.5 text-muted hover:bg-panel-2 hover:text-fg"
          >
            Close
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}
