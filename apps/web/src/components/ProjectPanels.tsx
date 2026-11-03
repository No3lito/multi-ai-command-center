"use client";

import { useState } from "react";
import { isApiError } from "@/lib/api";
import type { InboxItem, WorkspaceInfo, WorkspaceProject } from "@/lib/types";
import { familyLabel } from "@/lib/useWorkspace";
import { PanelSection } from "./PanelSection";

function ProjectOptions({ projects, families }: { projects: WorkspaceProject[]; families: string[] }) {
  return (
    <>
      {families.map((f) => (
        <optgroup key={f} label={familyLabel(f)}>
          {projects
            .filter((p) => p.family === f)
            .map((p) => (
              <option key={p.path} value={p.path}>
                {p.title}
              </option>
            ))}
        </optgroup>
      ))}
    </>
  );
}

function InboxRow({
  item,
  workspace,
  onFile,
}: {
  item: InboxItem;
  workspace: WorkspaceInfo;
  onFile: (name: string, projectPath: string) => Promise<unknown>;
}) {
  const [target, setTarget] = useState(item.suggested_project ?? workspace.projects[0]?.path ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const file = async () => {
    if (!target) return;
    setBusy(true);
    setError(null);
    try {
      await onFile(item.name, target);
    } catch (e: unknown) {
      setError(isApiError(e) ? e.message : "Could not file it.");
      setBusy(false);
    }
  };
  return (
    <li data-testid="inbox-item" className="rounded-md border border-line bg-bg p-2 text-xs">
      <p className="truncate font-medium" title={item.name}>
        {item.name}
      </p>
      <div className="mt-1 flex items-center gap-1.5">
        <select
          aria-label={`Project for ${item.name}`}
          data-testid="inbox-project"
          value={target}
          onChange={(e) => setTarget(e.target.value)}
          className="min-w-0 flex-1 rounded border border-line bg-bg px-1 py-1 text-xs"
        >
          <ProjectOptions projects={workspace.projects} families={workspace.families} />
        </select>
        <button
          type="button"
          data-testid="inbox-file"
          disabled={busy || !target}
          onClick={() => void file()}
          className="shrink-0 rounded-md bg-accent px-2 py-1 text-[11px] font-medium text-white disabled:opacity-50"
        >
          {busy ? "Filing…" : "File it"}
        </button>
      </div>
      {item.suggested_project && item.suggested_project === target && (
        <p className="mt-0.5 text-[10px] text-muted">Suggested from the file name.</p>
      )}
      {error && <p className="mt-1 text-[11px] text-danger">{error}</p>}
    </li>
  );
}

/** Files dropped in the workspace inbox, each filed into a project with one click. */
export function InboxPanel({
  workspace,
  onFile,
}: {
  workspace: WorkspaceInfo;
  onFile: (name: string, projectPath: string) => Promise<unknown>;
}) {
  if (!workspace.structured || workspace.inbox.length === 0) return null;
  return (
    <PanelSection title="Inbox" count={workspace.inbox.length} testId="inbox-panel">
      <p className="mb-1.5 text-[11px] text-muted">New files in 00-INBOX. Pick the project and file each one.</p>
      <ul className="space-y-1.5">
        {workspace.inbox.map((item) => (
          <InboxRow key={item.name} item={item} workspace={workspace} onFile={onFile} />
        ))}
      </ul>
    </PanelSection>
  );
}

/** Which workspace project this room works on (Setup tab). */
export function ProjectPanel({
  workspace,
  projectPath,
  onChange,
}: {
  workspace: WorkspaceInfo;
  projectPath: string | null;
  onChange: (projectPath: string | null) => Promise<unknown>;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (!workspace.structured) return null;
  const current = workspace.projects.find((p) => p.path === projectPath) ?? null;
  const change = async (value: string) => {
    setBusy(true);
    setError(null);
    try {
      await onChange(value || null);
    } catch (e: unknown) {
      setError(isApiError(e) ? e.message : "Could not change the project.");
    } finally {
      setBusy(false);
    }
  };
  return (
    <PanelSection title="Project folder" testId="project-panel">
      <select
        aria-label="Project folder for this room"
        data-testid="project-select"
        value={projectPath ?? ""}
        disabled={busy}
        onChange={(e) => void change(e.target.value)}
        className="w-full rounded border border-line bg-bg px-1 py-1 text-xs"
      >
        <option value="">No project folder</option>
        <ProjectOptions projects={workspace.projects} families={workspace.families} />
      </select>
      <p className="mt-1 text-[11px] text-muted">
        {current
          ? `Runs here read ${current.title}'s card and files, and save briefs, decisions and outputs into ${current.path}.`
          : "Link a project so runs read its files and save their results there."}
      </p>
      {error && <p className="mt-1 text-[11px] text-danger">{error}</p>}
    </PanelSection>
  );
}

/** Short project label for the room header. */
export function projectTitle(workspace: WorkspaceInfo, projectPath: string | null | undefined): string | null {
  if (!projectPath) return null;
  return workspace.projects.find((p) => p.path === projectPath)?.title ?? projectPath.split("/").pop() ?? null;
}
