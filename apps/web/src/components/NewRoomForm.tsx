"use client";

import { useId, useRef, useState, type FormEvent } from "react";
import { api, isApiError } from "@/lib/api";
import { ROOM_NAME_MAX, RUN_BUDGET_DEFAULT, RUN_MAX_TURNS_DEFAULT, isAgentUsable, type Room } from "@/lib/types";
import { familyLabel, useWorkspace } from "@/lib/useWorkspace";

const NONE = "";
const NEW = "__new__";
const NEW_FAMILY = "__new_family__";

export function validateRoomName(raw: string): string | null {
  const name = raw.trim();
  if (name.length < 1) return "Enter a name.";
  if (name.length > ROOM_NAME_MAX) return `Names can be at most ${ROOM_NAME_MAX} characters.`;
  return null;
}

/**
 * New project in one form: name, family and (optionally) what to get done. "Create and start"
 * makes the room and its project folder (Claude and GPT join automatically) and starts a
 * Collaborate run on the goal; "Create only" just makes the room.
 */
export function NewRoomForm({ onCreated, onDone }: { onCreated: (room: Room) => void; onDone?: () => void }) {
  const [name, setName] = useState("");
  const [goal, setGoal] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const { workspace, reload } = useWorkspace();
  const [project, setProject] = useState<string>(NEW);
  const [family, setFamily] = useState<string>("");
  const [newFamily, setNewFamily] = useState("");
  // The room created by a "Create and start" whose run did not start: retry starts the run only.
  const [pendingRoom, setPendingRoom] = useState<Room | null>(null);
  const sending = useRef(false);
  const inputId = useId();
  const errorId = useId();

  const famChoice = family || workspace.families[0] || NEW_FAMILY;

  async function startRun(room: Room, text: string) {
    const [detail, agents] = await Promise.all([api.getRoom(room.id), api.listAgents()]);
    const inRoom = new Set(detail.members.map((m) => m.id));
    const usable = agents.filter((a) => inRoom.has(a.id) && isAgentUsable(a));
    const planner = usable.find((a) => a.display_name.toLowerCase().startsWith("claude")) ?? usable[0];
    const critic = usable.find((a) => a.id !== planner?.id && a.display_name.toLowerCase().startsWith("gpt"));
    const second = critic ?? usable.find((a) => a.id !== planner?.id);
    if (!planner || !second) throw new Error("Two working agents are needed. The room was created without a run.");
    await api.createRun(room.id, {
      goal: text,
      workflow: "collab",
      planner_id: planner.id,
      critic_id: second.id,
      budget_usd: RUN_BUDGET_DEFAULT,
      max_turns: RUN_MAX_TURNS_DEFAULT,
    });
  }

  async function submit(e: FormEvent, start: boolean) {
    e.preventDefault();
    if (sending.current) return; // one click, one room
    if (pendingRoom) {
      sending.current = true;
      setBusy(true);
      setError(null);
      try {
        await startRun(pendingRoom, goal.trim());
        setPendingRoom(null);
        setName("");
        setGoal("");
        onDone?.();
      } catch (err) {
        setError(isApiError(err) || err instanceof Error ? err.message : "Could not start the run.");
      } finally {
        sending.current = false;
        setBusy(false);
      }
      return;
    }
    const invalid = validateRoomName(name);
    if (invalid) {
      setError(invalid);
      return;
    }
    if (start && !goal.trim()) {
      setError("Write what you want done, or use Create only.");
      return;
    }
    const fam = famChoice === NEW_FAMILY ? newFamily.trim() : famChoice;
    if (workspace.structured && project === NEW && !fam) {
      setError("Enter a family name for the new project.");
      return;
    }
    sending.current = true;
    setBusy(true);
    setError(null);
    let room: Room | null = null;
    try {
      room = !workspace.structured
        ? await api.createRoom(name.trim())
        : project === NEW
          ? await api.createRoom(name.trim(), {
              new_project: { family: fam, name: name.trim(), ...(goal.trim() ? { goal: goal.trim() } : {}) },
            })
          : project
            ? await api.createRoom(name.trim(), { project_path: project })
            : await api.createRoom(name.trim());
      if (project === NEW) reload();
      onCreated(room);
      if (start) await startRun(room, goal.trim());
      setName("");
      setGoal("");
      onDone?.();
    } catch (err) {
      if (room) {
        setPendingRoom(room);
        setError(
          `The room was created, but the run did not start: ${
            isApiError(err) || err instanceof Error ? err.message : "unknown error"
          }`,
        );
      } else if (isApiError(err) && err.code === "room_exists") setError("A room with that name already exists.");
      else setError(isApiError(err) ? err.message : "Could not create it.");
    } finally {
      sending.current = false;
      setBusy(false);
    }
  }

  const field = "mt-0.5 block w-full rounded-md border border-line bg-bg px-2 py-1.5 text-sm text-fg";
  return (
    <form onSubmit={(e) => void submit(e, !!goal.trim())} className="space-y-2 p-3" noValidate>
      <label htmlFor={inputId} className="block text-xs font-medium text-muted">
        Name
        <input
          id={inputId}
          data-testid="new-room-name"
          value={name}
          maxLength={ROOM_NAME_MAX + 20}
          placeholder="e.g. Polymarket bot"
          disabled={!!pendingRoom}
          onChange={(e) => {
            setName(e.target.value);
            if (error) setError(null);
          }}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? errorId : undefined}
          className={field}
          autoFocus
        />
      </label>
      {workspace.structured && (
        <div className="space-y-2" data-testid="new-room-project-box">
          <label className="block text-xs font-medium text-muted">
            Project folder
            <select
              data-testid="new-room-project"
              value={project}
              disabled={!!pendingRoom}
              onChange={(e) => setProject(e.target.value)}
              className={field}
            >
              <option value={NEW}>New project{name.trim() ? `: ${name.trim()}` : ""}</option>
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
            <label className="block text-xs font-medium text-muted">
              Family
              <select
                data-testid="new-room-family"
                value={famChoice}
                disabled={!!pendingRoom}
                onChange={(e) => setFamily(e.target.value)}
                className={field}
              >
                {workspace.families.map((f) => (
                  <option key={f} value={f}>
                    {familyLabel(f)}
                  </option>
                ))}
                <option value={NEW_FAMILY}>New family…</option>
              </select>
              {famChoice === NEW_FAMILY && (
                <input
                  data-testid="new-room-new-family"
                  value={newFamily}
                  maxLength={60}
                  placeholder="Family name, e.g. Fantasy sports"
                  onChange={(e) => setNewFamily(e.target.value)}
                  className={field}
                />
              )}
            </label>
          )}
        </div>
      )}
      <label className="block text-xs font-medium text-muted">
        What do you want done? <span className="font-normal">(optional)</span>
        <textarea
          data-testid="new-room-goal"
          value={goal}
          rows={3}
          maxLength={4000}
          placeholder="e.g. Find the three best Polymarket strategies to paper test"
          onChange={(e) => setGoal(e.target.value)}
          className={field}
        />
      </label>
      <p className="text-[11px] text-muted" data-testid="new-room-preview">
        {goal.trim()
          ? `Claude and GPT will collaborate on it right away · budget $${RUN_BUDGET_DEFAULT.toFixed(2)}`
          : "Claude and GPT join the room. Add a goal to start them right away."}
      </p>
      {error && (
        <p id={errorId} role="alert" className="text-xs text-danger">
          {error}
        </p>
      )}
      <div className="flex items-center justify-end gap-2 pt-1">
        {!pendingRoom && (
          <button
            type="button"
            data-testid="new-room-submit"
            disabled={busy}
            onClick={(e) => void submit(e as unknown as FormEvent, false)}
            className="rounded-md border border-line px-3 py-1.5 text-sm font-medium hover:bg-panel-2 disabled:opacity-50"
          >
            Create only
          </button>
        )}
        <button
          type="submit"
          data-testid="new-room-start"
          disabled={busy || !goal.trim()}
          className="rounded-md bg-accent px-3 py-1.5 text-sm font-semibold text-accent-fg hover:opacity-90 disabled:opacity-50"
        >
          {busy ? "Working…" : pendingRoom ? "Retry starting the run" : "Create and start"}
        </button>
      </div>
    </form>
  );
}
