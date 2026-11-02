"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import type { Message, PrincipalKind } from "@/lib/types";
import type { PendingMessage } from "@/lib/useOutbox";

const NEAR_BOTTOM_PX = 120;

const KIND_LABEL: Record<PrincipalKind, string> = {
  owner: "owner",
  human: "human",
  agent: "agent",
  external: "external",
  system: "system",
};

const KIND_STYLE: Record<PrincipalKind, string> = {
  owner: "bg-accent-soft text-accent",
  human: "bg-accent-soft text-accent",
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
}

export function MessageList({ messages, pending, loading, onRetry, onDiscard }: Props) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const nearBottomRef = useRef(true);
  const [showJump, setShowJump] = useState(false);
  const [announcement, setAnnouncement] = useState("");
  const seenCountRef = useRef<number | null>(null);

  const scrollToBottom = useCallback((smooth: boolean) => {
    const el = scrollRef.current;
    if (!el) return;
    if (typeof el.scrollTo === "function") el.scrollTo({ top: el.scrollHeight, behavior: smooth ? "smooth" : "auto" });
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

  // Auto-scroll when already near the bottom; otherwise offer "Jump to latest".
  useLayoutEffect(() => {
    if (total === 0) return;
    if (nearBottomRef.current) scrollToBottom(false);
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

        <ol className="space-y-0.5">
          {messages.map((m) => (
            <MessageRow key={m.id} message={m} />
          ))}
          {pending.map((p) => (
            <PendingRow key={p.key} item={p} onRetry={onRetry} onDiscard={onDiscard} />
          ))}
        </ol>
      </div>

      <div aria-live="polite" aria-atomic="true" className="sr-only">
        {announcement}
      </div>

      {showJump && (
        <button
          type="button"
          onClick={() => scrollToBottom(true)}
          className="absolute bottom-3 left-1/2 -translate-x-1/2 rounded-full border border-line bg-panel px-3 py-1 text-xs font-medium shadow-md hover:bg-panel-2"
        >
          Jump to latest
        </button>
      )}
    </div>
  );
}

function MessageRow({ message }: { message: Message }) {
  const t = formatTime(message.created_at);
  return (
    <li
      data-testid="message-item"
      data-message-id={message.id}
      data-seq={message.seq}
      className="group rounded-md px-2 py-1.5 hover:bg-panel"
    >
      <div className="flex items-baseline gap-2">
        <span className="font-semibold">{message.sender.display_name}</span>
        <KindBadge kind={message.sender.kind} />
        {message.kind !== "chat" && (
          <span className="font-mono text-[10px] text-muted">{message.kind}</span>
        )}
        <time dateTime={message.created_at} title={t.full} className="text-xs text-muted">
          {t.short}
        </time>
        <span className="ml-auto font-mono text-[10px] text-muted opacity-0 group-hover:opacity-100">
          #{message.seq}
        </span>
      </div>
      <p className="whitespace-pre-wrap break-words">{message.body.text}</p>
    </li>
  );
}

function PendingRow({
  item,
  onRetry,
  onDiscard,
}: {
  item: PendingMessage;
  onRetry: (key: string) => void;
  onDiscard: (key: string) => void;
}) {
  const failed = item.status === "failed";
  return (
    <li
      data-testid="message-item"
      data-pending={item.status}
      className={`rounded-md px-2 py-1.5 ${failed ? "bg-danger-soft" : "opacity-60"}`}
    >
      <div className="flex items-baseline gap-2">
        <span className="font-semibold">You</span>
        <span className="text-xs text-muted">{failed ? "Not sent" : "Sending..."}</span>
      </div>
      <p className="whitespace-pre-wrap break-words">{item.text}</p>
      {failed && (
        <div className="mt-1 flex items-center gap-3 text-xs">
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
