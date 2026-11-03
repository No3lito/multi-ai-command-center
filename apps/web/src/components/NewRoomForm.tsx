"use client";

import { useId, useState, type FormEvent } from "react";
import { api, isApiError } from "@/lib/api";
import { ROOM_NAME_MAX, type Room } from "@/lib/types";
import { familyLabel, useWorkspace } from "@/lib/useWorkspace";

const NONE = "";
const NEW = "__new__";
const NEW_FAMILY = "__new_family__";

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
  const { workspace, reload } = useWorkspace();
  const [project, setProject] = useState<string>(NEW);
  const [family, setFamily] = useState<string>("");
  const [newFamily, setNewFamily] = useState("");
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
      const famChoice = family || workspace.families[0] || NEW_FAMILY;
      const fam = famChoice === NEW_FAMILY ? newFamily.trim() : famChoice;
      if (workspace.structured && project === NEW && !fam) {
        setError("Enter a family name for the new project.");
        return;
      }
      const room = !workspace.structured
        ? await api.createRoom(name.trim())
        : project === NEW
          ? await api.createRoom(name.trim(), { new_project: { family: fam, name: name.trim() } })
          : project
            ? await api.createRoom(name.trim(), { project_path: project })
            : await api.createRoom(name.trim());
      setName("");
      if (project === NEW) reload();
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
      {workspace.structured && name.trim() && (
        <div className="mt-1.5 space-y-1 px-1 text-[11px]" data-testid="new-room-project-box">
          <label className="block text-muted">
            Project folder
            <select
              data-testid="new-room-project"
              value={project}
              onChange={(e) => setProject(e.target.value)}
              className="mt-0.5 block w-full rounded border border-line bg-bg px-1 py-1 text-xs text-fg"
            >
              <option value={NEW}>New project: {name.trim()}</option>
              {workspace.families.map((f) => (
                <optgroup key={f} label={familyLabel(f)}>
                  {workspace.projects
                    .filter((p) => p.family === f)
                    .map((p) => (
                      <option key={p.path} value={p.path}>
                        {p.title}
                      </option>
                    ))}
                </optgroup>
              ))}
              <option value={NONE}>No project folder</option>
            </select>
          </label>
          {project === NEW && (
            <label className="block text-muted">
              Family
              <select
                data-testid="new-room-family"
                value={family || workspace.families[0] || NEW_FAMILY}
                onChange={(e) => setFamily(e.target.value)}
                className="mt-0.5 block w-full rounded border border-line bg-bg px-1 py-1 text-xs text-fg"
              >
                {workspace.families.map((f) => (
                  <option key={f} value={f}>
                    {familyLabel(f)}
                  </option>
                ))}
                <option value={NEW_FAMILY}>New family…</option>
              </select>
              {(family || workspace.families[0] || NEW_FAMILY) === NEW_FAMILY && (
                <input
                  data-testid="new-room-new-family"
                  value={newFamily}
                  maxLength={60}
                  placeholder="Family name, e.g. Fantasy sports"
                  onChange={(e) => setNewFamily(e.target.value)}
                  className="mt-1 block w-full rounded border border-line bg-bg px-1 py-1 text-xs text-fg"
                />
              )}
            </label>
          )}
        </div>
      )}
      {error && (
        <p id={errorId} role="alert" className="mt-1 px-1 text-xs text-danger">
          {error}
        </p>
      )}
    </form>
  );
}
