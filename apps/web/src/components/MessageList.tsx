"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState, type CSSProperties } from "react";
import { formatCount, formatUsd } from "@/lib/format";
import { foldRuns } from "@/lib/foldRuns";
import { isRunActive, type Message, type PrincipalKind, type Run } from "@/lib/types";
import type { PendingMessage } from "@/lib/useOutbox";
import { pendingSpeaker, speakerId, type SenderStyle, type Speaker } from "@/lib/senderStyle";
import { useSpeakerStyles } from "@/lib/useSpeakerStyles";
import { Avatar } from "./Avatar";
import { bottomLine } from "./DecisionsPanel";
import { Folded, Markdown } from "./Markdown";
import { VerdictPill } from "./VerdictPill";

const NEAR_BOTTOM_PX = 120;

const KIND_LABEL: Record<PrincipalKind, string> = {
  owner: "owner",
  human: "human",
  agent: "agent",
  external: "external",
  system: "system",
};

const KIND_STYLE: Record<PrincipalKind, string> = {
  owner: "bg-accent-soft text-accent-ink",
  human: "bg-accent-soft text-accent-ink",
  agent: "bg-ok-soft text-ok",
  external: "bg-warn-soft text-warn",
  system: "bg-panel-2 text-muted",
};

function formatTime(iso: string): { short: string; full: string } {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return { short: "", full: iso };
  const sameDay = d.toDateString() === new Date().toDateString();
  const short = sameDay
    ? d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })
    : d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  return { short, full: d.toLocaleString() };
}

export function KindBadge({ kind }: { kind: PrincipalKind }) {
  return (
    <span
      className={`rounded px-1 py-px font-mono text-[10px] font-medium uppercase tracking-wide ${
        KIND_STYLE[kind] ?? KIND_STYLE.system
      }`}
    >
      {KIND_LABEL[kind] ?? kind}
    </span>
  );
}

interface Props {
  messages: Message[];
  pending: PendingMessage[];
  loading: boolean;
  onRetry: (key: string) => void;
  onDiscard: (key: string) => void;
  /** When given, each finished workflow run is folded into one card (see foldRuns). */
  runs?: Run[];
  onArchive?: (runId: string) => Promise<unknown>;
  participants?: readonly Speaker[];
  speakerStyles?: ReadonlyMap<string, SenderStyle>;
}

export function MessageList({ messages, pending, loading, onRetry, onDiscard, runs, onArchive, participants = [], speakerStyles }: Props) {
  const senders = [...participants, ...messages.map((message) => message.sender)];
  const localStyles = useSpeakerStyles(senders, pending.length > 0);
  const styles = speakerStyles ?? localStyles;
  const pendingId = speakerId(pendingSpeaker(senders));
  const pendingStyle = styles.get(pendingId) ?? localStyles.get(pendingId)!;
  // Runs the owner watched in progress stay open after they finish; older ones start folded.
  const [seenActive, setSeenActive] = useState<ReadonlySet<string>>(() => new Set());
  const [openRuns, setOpenRuns] = useState<Record<string, boolean>>({});
  const activeIds = (runs ?? []).filter(isRunActive).map((r) => r.id);
  if (activeIds.some((id) => !seenActive.has(id))) setSeenActive(new Set([...seenActive, ...activeIds]));
  const items = runs ? foldRuns(messages, runs) : messages.map((message) => ({ type: "message" as const, message }));
  const scrollRef = useRef<HTMLDivElement>(null);
  const nearBottomRef = useRef(true);
  const [showJump, setShowJump] = useState(false);
  const [announcement, setAnnouncement] = useState("");
  const seenCountRef = useRef<number | null>(null);

  const scrollToBottom = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    if (typeof el.scrollTo === "function") el.scrollTo({ top: el.scrollHeight, behavior: "auto" });
    else el.scrollTop = el.scrollHeight;
    nearBottomRef.current = true;
    setShowJump(false);
  }, []);

  const onScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    const near = el.scrollHeight - el.scrollTop - el.clientHeight < NEAR_BOTTOM_PX;
    nearBottomRef.current = near;
    if (near) setShowJump(false);
  }, []);

  const lastId = messages[messages.length - 1]?.id;
  const total = messages.length + pending.length;

  // Auto-scroll only when already near the bottom; otherwise offer "New messages".
  useLayoutEffect(() => {
    if (total === 0) return;
    if (nearBottomRef.current) scrollToBottom();
    else setShowJump(true);
  }, [lastId, total, scrollToBottom]);

  // Announce new messages politely (not the initial history load).
  useEffect(() => {
    if (loading) return;
    const prev = seenCountRef.current;
    seenCountRef.current = messages.length;
    if (prev === null || messages.length <= prev) return;
    const latest = messages[messages.length - 1];
    if (!latest) return;
    const added = messages.length - prev;
    setAnnouncement(
      added === 1
        ? `New message from ${latest.sender.display_name}: ${latest.body.text.slice(0, 140)}`
        : `${added} new messages`,
    );
  }, [messages, loading]);

  return (
    <div className="relative min-h-0 flex-1">
      <div
        ref={scrollRef}
        onScroll={onScroll}
        data-testid="message-list"
        role="log"
        aria-label="Messages"
        aria-busy={loading || undefined}
        tabIndex={0}
        className="h-full overflow-y-auto px-3 py-3 sm:px-5"
      >
        {loading && messages.length === 0 && <p className="py-6 text-center text-muted">Loading messages...</p>}
        {!loading && total === 0 && (
          <div className="py-10 text-center">
            <p className="font-medium">No messages yet</p>
            <p className="text-muted">Say something to start the conversation.</p>
          </div>
        )}

        <ol>
          {items.map((item, i) =>
            item.type === "message" ? (
              <MessageRow
                key={item.message.id}
                message={item.message}
                style={styles.get(speakerId(item.message.sender))!}
                grouped={(() => {
                  const prev = items[i - 1];
                  return (
                    prev?.type === "message" &&
                    prev.message.sender.kind !== "system" &&
                    speakerId(prev.message.sender) === speakerId(item.message.sender)
                  );
                })()}
              />
            ) : (
              <RunFold
                key={item.runId}
                runId={item.runId}
                run={item.run}
                title={item.title}
                messages={item.messages}
                open={openRuns[item.runId] ?? seenActive.has(item.runId)}
                onToggle={(open) => setOpenRuns((prev) => ({ ...prev, [item.runId]: open }))}
                onArchive={onArchive}
                styles={styles}
              />
            ),
          )}
          {pending.map((p) => (
            <PendingRow key={p.key} item={p} style={pendingStyle} onRetry={onRetry} onDiscard={onDiscard} />
          ))}
        </ol>
      </div>

      <div aria-live="polite" aria-atomic="true" className="sr-only">
        {announcement}
      </div>

      {showJump && (
        <button
          type="button"
          onClick={() => scrollToBottom()}
          className="absolute bottom-3 left-1/2 -translate-x-1/2 rounded-full border border-line bg-panel px-3 py-1 text-xs font-medium shadow-md hover:bg-panel-2"
        >
          New messages ↓
        </button>
      )}
    </div>
  );
}

/** Semantic kinds/data, not message prose, determine actionable notices. */
function systemLabel(message: Message): string | null {
  if (message.kind === "error") return "Error";
  if (message.kind === "task.assign") return "Assignment";
  if (/approv|decision|permission/.test(message.kind) ||
      message.body.data?.requires_approval === true) return "Approval";
  return null;
}

const FOLD_STATUS: Record<string, string> = {
  completed: "Completed",
  failed: "Failed",
  cancelled: "Cancelled",
  budget_exceeded: "Over budget",
};

/** The summary line shown on a folded run card (same rule as the decisions panel). */
function briefLine(brief: string | null | undefined): string {
  return brief ? bottomLine(brief).slice(0, 300) : "";
}

/** One finished run, folded into a single card; its full conversation opens on demand. */
function RunFold({
  runId,
  run,
  title,
  messages,
  open,
  onToggle,
  onArchive,
  styles,
}: {
  runId: string;
  run: Run | null;
  title: string;
  messages: Message[];
  open: boolean;
  onToggle: (open: boolean) => void;
  onArchive?: (runId: string) => Promise<unknown>;
  styles: ReadonlyMap<string, SenderStyle>;
}) {
  const [archiving, setArchiving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const line = briefLine(run?.brief);
  const archive = async () => {
    if (!onArchive) return;
    setArchiving(true);
    setError(null);
    try {
      await onArchive(runId);
    } catch {
      setError("Could not archive this run.");
      setArchiving(false);
    }
  };
  return (
    <li
      data-testid="run-fold"
      data-run-id={runId}
      data-open={open}
      className="my-2 rounded-md border border-line bg-panel"
    >
      <div className="flex items-start gap-2 px-3 py-2">
        <div className="min-w-0 flex-1">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-muted">
            {run ? (FOLD_STATUS[run.status] ?? run.status) : "Earlier run"}
            {run &&
              ` · ${run.kind === "collab" ? "collaborate" : run.kind === "build" ? "design & build" : run.kind === "code" ? "code change" : "review & improve"}`}
            {run && ` · ${formatUsd(run.spent_usd)}`}
          </p>
          <p className="flex items-center gap-1.5 font-medium" title={title}>
            {run?.verdict && <VerdictPill verdict={run.verdict} />}
            <span className="truncate">{title}</span>
          </p>
          {line && (
            <p data-testid="run-fold-line" className="mt-0.5 text-sm text-fg">
              {line}
            </p>
          )}
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1">
          <button
            type="button"
            data-testid="run-fold-toggle"
            aria-expanded={open}
            onClick={() => onToggle(!open)}
            className="rounded-md border border-line px-2 py-0.5 text-xs hover:bg-panel-2"
          >
            {open ? "Hide conversation" : `Show conversation (${messages.length})`}
          </button>
          {onArchive && run && (
            <button
              type="button"
              data-testid="run-fold-archive"
              disabled={archiving}
              onClick={() => void archive()}
              className="text-[11px] text-muted underline disabled:opacity-50"
              title="Hide this run from the chat. Find it again under History."
            >
              Archive
            </button>
          )}
        </div>
      </div>
      {error && <p className="px-3 pb-2 text-xs text-danger">{error}</p>}
      {open && (
        <ol className="space-y-0.5 border-t border-line px-2 py-2">
          {messages.map((m, index) => (
            <MessageRow
              key={m.id}
              message={m}
              style={styles.get(speakerId(m.sender))!}
              grouped={(() => {
                const previous = messages[index - 1];
                return previous !== undefined &&
                  m.sender.kind !== "system" &&
                  previous.sender.kind !== "system" &&
                  speakerId(previous.sender) === speakerId(m.sender);
              })()}
            />
          ))}
        </ol>
      )}
    </li>
  );
}

function dataString(data: Record<string, unknown> | undefined, key: string): string | null {
  const v = data?.[key];
  return typeof v === "string" && v ? v : null;
}

/** True when the message says it came from the deterministic local stand-in. */
export function isSimulatedMessage(message: Message): boolean {
  return message.body.data?.simulated === true;
}

function MessageRow({ message, grouped = false, style }: {
  message: Message;
  grouped?: boolean;
  style: SenderStyle;
}) {
  if (message.sender.kind === "system") return <SystemNote message={message} />;
  return <ChatRow message={message} grouped={grouped} style={style} />;
}

export function SimulatedBadge() {
  return (
    <span
      data-testid="simulated-badge"
      title="Produced by the local stand-in, not a real AI provider. No cost."
      className="rounded border border-warn/40 bg-warn-soft px-1.5 py-px font-mono text-[10px] font-bold uppercase tracking-wider text-warn"
    >
      SIMULATED
    </span>
  );
}

function ChatRow({ message, grouped, style }: { message: Message; grouped: boolean; style: SenderStyle }) {
  const t = formatTime(message.created_at);
  const data = message.body.data;
  const isAgent = message.sender.kind === "agent";
  const provider = isAgent ? dataString(data, "provider") : null;
  const model = isAgent ? dataString(data, "model") : null;
  const simulated = isSimulatedMessage(message);
  const usage = isAgent ? message.usage : null;
  const tokens = usage ? (usage.input_tokens ?? 0) + (usage.output_tokens ?? 0) : 0;
  const mine = message.sender.kind === "owner" || message.sender.kind === "human";
  return (
    <li
      data-testid="message-item"
      data-message-id={message.id}
      data-seq={message.seq}
      data-sender-kind={message.sender.kind}
      data-sender-style={style.key}
      data-accent={style.color === "var(--speaker-rose)" ? "rose" : undefined}
      data-simulated={simulated || undefined}
      data-correlation-id={message.correlation_id ?? undefined}
      data-reply-to={message.reply_to ?? undefined}
      data-grouped={grouped || undefined}
      style={{ "--speaker-color": style.color } as CSSProperties}
      className={`group speaker-card ${grouped ? "speaker-continuation" : ""} ${mine ? "speaker-owner" : ""}`}
    >
      <div className="min-w-0">
        {!grouped && (
          <div className="mb-2 flex flex-wrap items-center gap-x-2 gap-y-1">
            <Avatar style={style} label={message.sender.display_name} />
            <span className="inline-flex items-center gap-2 font-semibold text-fg">
              <span
                aria-hidden="true"
                data-testid="agent-dot"
                className="h-2 w-2 shrink-0 rounded-full"
                style={{ background: style.color }}
              />
              {message.sender.display_name}
            </span>
            <span className="speaker-role">{mine ? "You" : isAgent ? "AI" : "System"}</span>
            <KindBadge kind={message.sender.kind} />
          </div>
        )}
        <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
          {(provider || model) && (
            <span data-testid="message-model" className="font-mono text-[10px] text-muted">
              {[provider, model].filter(Boolean).join(" / ")}
            </span>
          )}
          {simulated && <SimulatedBadge />}
          {message.kind !== "chat" && <span className="font-mono text-[10px] text-muted">{message.kind}</span>}
          <time dateTime={message.created_at} title={t.full} className="text-xs text-muted">
            {t.short}
          </time>
          <span className="ml-auto font-mono text-[10px] text-muted">
            #{message.seq}
          </span>
        </div>
        <Folded text={message.body.text}>
          <Markdown text={message.body.text} />
        </Folded>
        {usage && (
          <p data-testid="message-usage" className="mt-1 font-mono text-[10px] text-muted">
            {formatCount(usage.input_tokens)} in, {formatCount(usage.output_tokens)} out ({formatCount(tokens)} tokens)
            {" · "}
            {simulated ? "no cost (simulated)" : formatUsd(usage.cost_usd)}
          </p>
        )}
      </div>
    </li>
  );
}

function SystemNote({ message }: { message: Message }) {
  const t = formatTime(message.created_at);
  const isError = message.kind === "error";
  const label = systemLabel(message);
  return (
    <li
      data-testid="message-item"
      data-message-id={message.id}
      data-seq={message.seq}
      data-sender-kind="system"
      data-note-kind={message.kind}
      data-correlation-id={message.correlation_id ?? undefined}
      data-system-tier={label ? "action" : "routine"}
      className={`group system-note text-muted ${label ? "system-action" : ""}`}
    >
      <span aria-hidden="true" className="mt-px shrink-0">
        {isError ? <ErrorIcon /> : <NoteIcon kind={message.kind} />}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline gap-x-2">
          <span className="font-semibold">{message.sender.display_name}</span>
          <span className="speaker-role">System</span>
          {label && <strong>{label}</strong>}
          <span className="font-mono text-[13px]">{message.kind}</span>
          <time dateTime={message.created_at} title={t.full} className="text-[13px]">
            {t.short}
          </time>
          <span className="ml-auto font-mono text-[10px] opacity-0 group-hover:opacity-100">#{message.seq}</span>
        </div>
        <p className={`whitespace-pre-wrap break-words ${isError ? "" : "text-fg/80"}`}>{message.body.text}</p>
      </div>
    </li>
  );
}

function NoteIcon({ kind }: { kind: Message["kind"] }) {
  if (kind === "task.result") {
    return (
      <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
        <path d="M2.5 6.5l2.2 2.2L9.5 3.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      </svg>
    );
  }
  if (kind === "task.assign") {
    return (
      <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
        <path d="M2 6h7M6.5 3l3 3-3 3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      </svg>
    );
  }
  return (
    <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
      <circle cx="6" cy="6" r="4" stroke="currentColor" strokeWidth="1.5" />
      <path d="M6 4v2.2l1.4 1" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
    </svg>
  );
}

function ErrorIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
      <circle cx="6" cy="6" r="4.5" stroke="currentColor" strokeWidth="1.5" />
      <path d="M6 3.5v3M6 8.3v.2" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}

function PendingRow({
  item,
  style,
  onRetry,
  onDiscard,
}: {
  item: PendingMessage;
  style: SenderStyle;
  onRetry: (key: string) => void;
  onDiscard: (key: string) => void;
}) {
  const failed = item.status === "failed";
  return (
    <li
      data-testid="message-item"
      data-pending={item.status}
      data-sender-style={style.key}
      data-accent={style.color === "var(--speaker-rose)" ? "rose" : undefined}
      style={{ "--speaker-color": style.color } as CSSProperties}
      className="speaker-card speaker-owner"
    >
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <Avatar style={style} label="You" />
        <span className="font-semibold">You</span>
        <span className="speaker-role">You</span>
        <span className="text-xs text-muted">{failed ? "Not sent" : "Sending..."}</span>
      </div>
      <p className="whitespace-pre-wrap break-words">{item.text}</p>
      {failed && (
        <div className="mt-1 flex flex-wrap items-center gap-3 text-xs">
          <span className="text-danger">{item.error}</span>
          <button type="button" onClick={() => onRetry(item.key)} className="font-medium text-fg underline">
            Retry
          </button>
          <button type="button" onClick={() => onDiscard(item.key)} className="text-muted underline">
            Discard
          </button>
        </div>
      )}
    </li>
  );
}
