"use client";

import { useState } from "react";
import type { Principal, Room } from "@/lib/types";
import { Logo } from "./Logo";
import { NewRoomForm } from "./NewRoomForm";
import { Modal } from "./RightTabs";

type RoomsState = { kind: "loading" } | { kind: "error"; message: string } | { kind: "ready"; rooms: Room[] };

interface Props {
  open: boolean;
  principal: Principal;
  rooms: RoomsState;
  selectedId: string | null;
  onSelect: (id: string) => void;
  onCreated: (room: Room) => void;
  onRetry: () => void;
  onSignOut: () => void;
}

export function Sidebar({ open, principal, rooms, selectedId, onSelect, onCreated, onRetry, onSignOut }: Props) {
  const [creating, setCreating] = useState(false);
  return (
    <>
      <aside
        id="left-sidebar"
        aria-label="Rooms"
        className={`fixed inset-y-0 left-0 z-40 flex w-64 shrink-0 flex-col border-r border-line bg-panel transition-transform lg:static lg:translate-x-0 ${
          open ? "translate-x-0" : "-translate-x-full invisible lg:visible"
        }`}
      >
        <div className="flex h-12 items-center gap-2 border-b border-line px-3">
          <Logo />
          <span className="truncate text-sm font-semibold">Multi-AI Command Center</span>
        </div>

        <nav aria-label="Room list" className="min-h-0 flex-1 overflow-y-auto px-2 py-3">
          <button
            type="button"
            data-testid="new-project-open"
            onClick={() => setCreating(true)}
            className="mb-3 flex w-full items-center justify-center gap-1.5 rounded-md bg-accent px-2 py-2 text-sm font-semibold text-white hover:opacity-90"
          >
            <span aria-hidden="true" className="text-base leading-none">
              +
            </span>
            New project
          </button>
          <h2 className="px-2 pb-1 text-[11px] font-semibold uppercase tracking-wider text-muted">Rooms</h2>

          {rooms.kind === "loading" && <p className="px-2 py-1 text-muted">Loading rooms...</p>}

          {rooms.kind === "error" && (
            <div className="mx-1 rounded-md bg-danger-soft px-2 py-2 text-sm text-danger" role="alert">
              <p>{rooms.message}</p>
              <button type="button" onClick={onRetry} className="mt-1 font-medium underline">
                Retry
              </button>
            </div>
          )}

          {rooms.kind === "ready" && rooms.rooms.length === 0 && (
            <p className="px-2 py-1 text-muted">No rooms yet. Use New project above.</p>
          )}

          {rooms.kind === "ready" && rooms.rooms.length > 0 && (
            <ul data-testid="room-list" className="space-y-px">
              {rooms.rooms.map((room) => {
                const active = room.id === selectedId;
                return (
                  <li key={room.id}>
                    <button
                      type="button"
                      data-testid="room-item"
                      data-room-id={room.id}
                      aria-current={active ? "page" : undefined}
                      onClick={() => onSelect(room.id)}
                      className={`flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left ${
                        active ? "bg-accent-soft font-medium text-fg" : "text-muted hover:bg-panel-2 hover:text-fg"
                      }`}
                    >
                      <span aria-hidden="true" className="font-mono text-muted">
                        #
                      </span>
                      <span className="min-w-0 flex-1 truncate">{room.name}</span>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </nav>

        <div className="flex items-center gap-2 border-t border-line px-3 py-2">
          <span
            aria-hidden="true"
            className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-accent-soft text-xs font-semibold text-accent"
          >
            {principal.display_name.slice(0, 1).toUpperCase()}
          </span>
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium">{principal.display_name}</p>
            <p className="text-xs text-muted">{principal.kind}</p>
          </div>
          <button
            type="button"
            onClick={onSignOut}
            className="rounded-md border border-line px-2 py-1 text-xs font-medium hover:bg-panel-2"
          >
            Sign out
          </button>
        </div>
      </aside>
      {creating && (
        <Modal title="New project" onClose={() => setCreating(false)}>
          <NewRoomForm onCreated={onCreated} onDone={() => setCreating(false)} />
        </Modal>
      )}
    </>
  );
}
