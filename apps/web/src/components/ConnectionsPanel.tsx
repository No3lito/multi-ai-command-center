"use client";

import { useCallback, useEffect, useId, useState, type FormEvent } from "react";
import { isApiError } from "@/lib/api";
import type { Connection } from "@/lib/types";
import { ErrorText, PanelSection, Pill } from "./PanelSection";

export interface ConnectionsApi {
  listConnections: (signal?: AbortSignal) => Promise<Connection[]>;
  createConnection: (displayName: string, roomIds?: string[]) => Promise<Connection>;
  rotateConnection: (id: string) => Promise<Connection>;
  revokeConnection: (id: string) => Promise<Connection>;
}

interface Props {
  api: ConnectionsApi;
  roomId: string | null;
  roomName: string | null;
  /** Principal ids that are members of the current room. */
  memberIds: ReadonlySet<string>;
  /** Adds a principal to the current room (same endpoint as adding an agent). */
  onAddToRoom: (principalId: string) => Promise<unknown>;
  /** Called after a connection changes, so the room's members reload. */
  onChanged?: () => void;
}

/** External agents such as Grok Bot, connected over MCP with a token shown once. */
export function ConnectionsPanel({ api, roomId, roomName, memberIds, onAddToRoom, onChanged }: Props) {
  const [items, setItems] = useState<Connection[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState("Grok Bot");
  const [busy, setBusy] = useState(false);
  const [fresh, setFresh] = useState<Connection | null>(null);
  const [confirming, setConfirming] = useState<string | null>(null);
  const nameId = useId();

  const reload = useCallback(
    (signal?: AbortSignal) =>
      api
        .listConnections(signal)
        .then((list) => {
          setItems(list);
          setError(null);
        })
        .catch((e: unknown) => {
          if (signal?.aborted) return;
          setError(isApiError(e) ? e.message : "Could not load connections.");
        }),
    [api],
  );

  useEffect(() => {
    const abort = new AbortController();
    void reload(abort.signal);
    return () => abort.abort();
  }, [reload]);

  async function act(fn: () => Promise<Connection>, showToken: boolean) {
    setBusy(true);
    setError(null);
    try {
      const c = await fn();
      if (showToken) setFresh(c);
      await reload();
      onChanged?.();
    } catch (e) {
      setError(isApiError(e) ? e.message : "That did not work.");
    } finally {
      setBusy(false);
      setConfirming(null);
    }
  }

  function create(e: FormEvent) {
    e.preventDefault();
    const trimmed = name.trim();
    if (!trimmed || busy) return;
    void act(() => api.createConnection(trimmed, roomId ? [roomId] : []), true);
  }

  return (
    <PanelSection title="Connections" count={items?.length} testId="connections-panel">
      <p className="mb-2 text-[11px] text-muted">
        Outside agents, such as your Grok Bot, join rooms through a secure MCP link. Each gets a private token.
      </p>
      {fresh?.token && (
        <div data-testid="connection-token" className="mb-2 rounded-md border border-warn bg-warn-soft p-2 text-xs">
          <p className="mb-1 font-semibold text-warn">
            Token for {fresh.display_name}. It is shown only once: copy it now.
          </p>
          <code className="block break-all rounded bg-bg px-1 py-0.5 font-mono text-[11px]">{fresh.token}</code>
          <div className="mt-1 flex gap-2">
            <button
              type="button"
              className="rounded border border-line px-2 py-0.5 text-[11px]"
              onClick={() => void navigator.clipboard?.writeText(fresh.token ?? "")}
            >
              Copy token
            </button>
            <button type="button" className="text-[11px] underline" onClick={() => setFresh(null)}>
              I saved it
            </button>
          </div>
          <p className="mt-1 text-[10px] text-muted">
            MCP endpoint on this computer: http://localhost:{fresh.mcp_port}
            {fresh.mcp_path}. Grok Bot needs it through a secure tunnel; never share the token in chats or files.
          </p>
        </div>
      )}
      {items && items.length > 0 && (
        <ul className="mb-2 space-y-1.5">
          {items.map((c) => {
            const here = memberIds.has(c.id);
            return (
              <li
                key={c.id}
                data-testid="connection-item"
                data-status={c.status}
                className="rounded-md border border-line bg-bg px-2 py-1.5 text-xs"
              >
                <div className="flex items-center gap-1.5">
                  <span className="font-medium">{c.display_name}</span>
                  <Pill tone={c.status === "active" ? "ok" : "muted"}>
                    {c.status === "active" ? "Connected" : "Disconnected"}
                  </Pill>
                </div>
                <p className="text-[10px] text-muted">
                  {c.last_used_at ? `Last seen ${new Date(c.last_used_at).toLocaleString()}` : "Not used yet"} · Rooms:{" "}
                  {c.rooms.map((r) => r.name).join(", ") || "none"}
                </p>
                <div className="mt-1 flex flex-wrap gap-2 text-[11px]">
                  {roomId && !here && c.status === "active" && (
                    <button
                      type="button"
                      disabled={busy}
                      className="underline"
                      onClick={() =>
                        void (async () => {
                          setBusy(true);
                          try {
                            await onAddToRoom(c.id);
                            await reload();
                          } catch (e) {
                            setError(isApiError(e) ? e.message : "Could not add it to this room.");
                          } finally {
                            setBusy(false);
                          }
                        })()
                      }
                    >
                      Add to {roomName ?? "this room"}
                    </button>
                  )}
                  <button
                    type="button"
                    disabled={busy}
                    className="underline"
                    onClick={() => void act(() => api.rotateConnection(c.id), true)}
                  >
                    {c.status === "active" ? "New token" : "Reconnect"}
                  </button>
                  {c.status === "active" &&
                    (confirming === c.id ? (
                      <button
                        type="button"
                        disabled={busy}
                        data-testid="connection-revoke-confirm"
                        className="font-semibold text-danger underline"
                        onClick={() => void act(() => api.revokeConnection(c.id), false)}
                      >
                        Confirm disconnect
                      </button>
                    ) : (
                      <button type="button" className="text-danger underline" onClick={() => setConfirming(c.id)}>
                        Disconnect
                      </button>
                    ))}
                </div>
              </li>
            );
          })}
        </ul>
      )}
      <form onSubmit={create} className="flex items-end gap-2">
        <div className="min-w-0 flex-1">
          <label htmlFor={nameId} className="mb-0.5 block text-[11px] font-medium text-muted">
            New connection
          </label>
          <input
            id={nameId}
            data-testid="connection-name"
            value={name}
            maxLength={40}
            onChange={(e) => setName(e.target.value)}
            className="w-full rounded-md border border-line bg-bg px-2 py-1 text-sm"
          />
        </div>
        <button
          type="submit"
          data-testid="connection-create"
          disabled={busy || !name.trim()}
          className="rounded-md bg-accent px-3 py-1 text-sm font-medium text-accent-fg disabled:opacity-40"
        >
          Connect
        </button>
      </form>
      {error && <ErrorText>{error}</ErrorText>}
    </PanelSection>
  );
}
