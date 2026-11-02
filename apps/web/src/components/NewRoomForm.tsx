"use client";

import { useId, useState, type FormEvent } from "react";
import { api, isApiError } from "@/lib/api";
import { ROOM_NAME_MAX, type Room } from "@/lib/types";

export function validateRoomName(raw: string): string | null {
  const name = raw.trim();
  if (name.length < 1) return "Enter a room name.";
  if (name.length > ROOM_NAME_MAX) return `Room names can be at most ${ROOM_NAME_MAX} characters.`;
  return null;
}

export function NewRoomForm({ onCreated }: { onCreated: (room: Room) => void }) {
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const inputId = useId();
  const errorId = useId();

  async function submit(e: FormEvent) {
    e.preventDefault();
    const invalid = validateRoomName(name);
    if (invalid) {
      setError(invalid);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const room = await api.createRoom(name.trim());
      setName("");
      onCreated(room);
    } catch (err) {
      if (isApiError(err) && err.code === "room_exists") setError("A room with that name already exists.");
      else setError(isApiError(err) ? err.message : "Could not create the room.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="mt-4 border-t border-line px-1 pt-3" noValidate>
      <label htmlFor={inputId} className="px-1 text-[11px] font-semibold uppercase tracking-wider text-muted">
        New room
      </label>
      <div className="mt-1 flex gap-1">
        <input
          id={inputId}
          data-testid="new-room-name"
          value={name}
          maxLength={ROOM_NAME_MAX + 20}
          placeholder="Room name"
          onChange={(e) => {
            setName(e.target.value);
            if (error) setError(null);
          }}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? errorId : undefined}
          className="min-w-0 flex-1 rounded-md border border-line bg-bg px-2 py-1 text-sm placeholder:text-muted"
        />
        <button
          type="submit"
          data-testid="new-room-submit"
          disabled={busy}
          className="rounded-md bg-accent px-2 py-1 text-sm font-medium text-accent-fg hover:opacity-90 disabled:opacity-50"
        >
          {busy ? "Adding" : "Add"}
        </button>
      </div>
      {error && (
        <p id={errorId} role="alert" className="mt-1 px-1 text-xs text-danger">
          {error}
        </p>
      )}
    </form>
  );
}
