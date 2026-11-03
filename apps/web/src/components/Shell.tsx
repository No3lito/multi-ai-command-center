"use client";

import { useCallback, useEffect, useState } from "react";
import { api, isApiError } from "@/lib/api";
import type { Principal, Room } from "@/lib/types";
import { readRoomParam, writeRoomParam } from "@/lib/urlState";
import { Sidebar } from "./Sidebar";
import { RoomView } from "./RoomView";

type RoomsState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ready"; rooms: Room[] };

export function Shell({ principal, onSignOut }: { principal: Principal; onSignOut: () => void }) {
  const [rooms, setRooms] = useState<RoomsState>({ kind: "loading" });
  const [selected, setSelected] = useState<string | null>(null);
  const [leftOpen, setLeftOpen] = useState(false);
  const [rightOpen, setRightOpen] = useState(false);

  const loadRooms = useCallback(async () => {
    try {
      const list = await api.listRooms();
      setRooms({ kind: "ready", rooms: list });
      return list;
    } catch (e) {
      setRooms({ kind: "error", message: isApiError(e) ? e.message : "Could not load rooms." });
      return null;
    }
  }, []);

  // Initial load: choose the room from ?room=, else General, else the first room.
  useEffect(() => {
    let active = true;
    // loadRooms only sets state after its first await, so this does not cascade.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadRooms().then((list) => {
      if (!active || !list) return;
      const fromUrl = readRoomParam();
      const initial =
        fromUrl ?? list.find((r) => r.name === "General")?.id ?? list[0]?.id ?? null;
      setSelected(initial);
      if (initial && initial !== fromUrl) writeRoomParam(initial, "replace");
    });
    return () => {
      active = false;
    };
  }, [loadRooms]);

  useEffect(() => {
    const onPop = () => setSelected(readRoomParam());
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const selectRoom = useCallback((id: string) => {
    setSelected(id);
    writeRoomParam(id, "push");
    setLeftOpen(false);
  }, []);

  const onRoomCreated = useCallback(
    (room: Room) => {
      setRooms((prev) =>
        prev.kind === "ready"
          ? {
              kind: "ready",
              rooms: [...prev.rooms.filter((r) => r.id !== room.id), room].sort((a, b) =>
                a.name.localeCompare(b.name),
              ),
            }
          : prev,
      );
      selectRoom(room.id);
    },
    [selectRoom],
  );

  // Escape closes the mobile drawers.
  useEffect(() => {
    if (!leftOpen && !rightOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setLeftOpen(false);
        setRightOpen(false);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [leftOpen, rightOpen]);

  const roomList = rooms.kind === "ready" ? rooms.rooms : [];
  const current = roomList.find((r) => r.id === selected) ?? null;

  return (
    <div className="flex h-dvh overflow-hidden">
      <a
        href="#composer-input"
        className="sr-only-focusable absolute left-2 top-2 z-50 rounded bg-accent px-2 py-1 text-accent-fg"
      >
        Skip to message composer
      </a>

      {(leftOpen || rightOpen) && (
        <button
          type="button"
          aria-label="Close panel"
          tabIndex={-1}
          onClick={() => {
            setLeftOpen(false);
            setRightOpen(false);
          }}
          className="fixed inset-0 z-30 bg-black/40 md:hidden"
        />
      )}

      <Sidebar
        open={leftOpen}
        principal={principal}
        rooms={rooms}
        selectedId={selected}
        onSelect={selectRoom}
        onCreated={onRoomCreated}
        onRetry={() => void loadRooms()}
        onSignOut={onSignOut}
      />

      <RoomView
        key={selected ?? "none"}
        roomId={selected}
        roomSummary={current}
        roomsLoaded={rooms.kind === "ready"}
        hasRooms={roomList.length > 0}
        rightOpen={rightOpen}
        onToggleLeft={() => setLeftOpen((v) => !v)}
        onToggleRight={() => setRightOpen((v) => !v)}
        onRoomMissing={() => void loadRooms()}
      />
    </div>
  );
}
