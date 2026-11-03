"use client";

import { useCallback, useEffect, useState } from "react";
import { isApiError } from "@/lib/api";
import type { FileEntry, FilesListing } from "@/lib/types";

export interface PickedFile {
  path: string;
  size: number;
}

interface Props {
  listFiles: (path?: string, signal?: AbortSignal) => Promise<FilesListing>;
  selected: PickedFile[];
  onChange: (files: PickedFile[]) => void;
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** Rough tokens for text: about 4 characters per token. */
export function estimateTokens(bytes: number): number {
  return Math.ceil(bytes / 4);
}

/** Pick text files from the owner's shared folder (read-only) for Claude and GPT to read. */
export function AttachmentsPicker({ listFiles, selected, onChange }: Props) {
  const [open, setOpen] = useState(false);
  const [listing, setListing] = useState<FilesListing | null>(null);
  const [path, setPath] = useState("");
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    (p: string, signal?: AbortSignal) =>
      listFiles(p, signal)
        .then((l) => {
          setListing(l);
          setPath(l.path);
          setError(null);
        })
        .catch((e: unknown) => {
          if (!signal?.aborted) setError(isApiError(e) ? e.message : "Could not list files.");
        }),
    [listFiles],
  );

  useEffect(() => {
    const abort = new AbortController();
    void load("", abort.signal);
    return () => abort.abort();
  }, [load]);

  if (listing && !listing.enabled) return null;

  const totalBytes = selected.reduce((n, f) => n + f.size, 0);
  const isPicked = (p: string) => selected.some((f) => f.path === p);
  const toggle = (e: FileEntry) =>
    onChange(
      isPicked(e.path)
        ? selected.filter((f) => f.path !== e.path)
        : [...selected, { path: e.path, size: e.size ?? 0 }].slice(0, listing?.max_files ?? 10),
    );
  const overLimit = listing ? totalBytes > listing.max_chars : false;
  const parent = path.includes("/") ? path.slice(0, path.lastIndexOf("/")) : "";

  return (
    <div data-testid="attachments" className="rounded-md border border-line p-2">
      <div className="flex items-center gap-2">
        <span className="text-[11px] font-medium text-muted">Files for Claude and GPT to read</span>
        <button
          type="button"
          data-testid="attachments-toggle"
          className="ml-auto text-[11px] underline"
          onClick={() => setOpen((o) => !o)}
        >
          {open ? "Done" : selected.length ? `Change (${selected.length})` : "Attach files"}
        </button>
      </div>
      {selected.length > 0 && (
        <ul className="mt-1 space-y-0.5 text-[11px]">
          {selected.map((f) => (
            <li key={f.path} data-testid="attachment-chip" className="flex gap-2">
              <span className="min-w-0 flex-1 truncate font-mono">{f.path}</span>
              <span className="text-muted">{formatSize(f.size)}</span>
            </li>
          ))}
          <li className={overLimit ? "text-danger" : "text-muted"} data-testid="attachments-estimate">
            About {estimateTokens(totalBytes).toLocaleString()} tokens, read by each reviewer step
            {overLimit && listing ? `; over the ${listing.max_chars.toLocaleString()}-character limit` : ""}.
          </li>
        </ul>
      )}
      {open && (
        <div className="mt-2 max-h-56 overflow-y-auto border-t border-line pt-1 text-xs">
          <p className="mb-1 font-mono text-[10px] text-muted">/{path}</p>
          {path && (
            <button type="button" className="mb-1 block text-[11px] underline" onClick={() => void load(parent)}>
              Up one folder
            </button>
          )}
          {listing?.entries.length === 0 && <p className="text-muted">This folder is empty.</p>}
          <ul className="space-y-0.5">
            {listing?.entries.map((e) =>
              e.type === "dir" ? (
                <li key={e.path}>
                  <button type="button" className="text-left underline" onClick={() => void load(e.path)}>
                    {e.name}/
                  </button>
                </li>
              ) : (
                <li key={e.path}>
                  <label className={`flex items-center gap-2 ${e.readable ? "" : "text-muted"}`}>
                    <input
                      type="checkbox"
                      data-testid="attachment-checkbox"
                      disabled={!e.readable}
                      checked={isPicked(e.path)}
                      onChange={() => toggle(e)}
                    />
                    <span className="min-w-0 flex-1 truncate">{e.name}</span>
                    <span className="text-[10px] text-muted">
                      {e.readable ? formatSize(e.size ?? 0) : "not a text file"}
                    </span>
                  </label>
                </li>
              ),
            )}
          </ul>
        </div>
      )}
      {error && <p className="mt-1 text-[11px] text-danger">{error}</p>}
      <p className="mt-1 text-[10px] text-muted">
        Read-only. Contents are sent to Anthropic and OpenAI with each reviewer step, not to connected agents.
      </p>
    </div>
  );
}
