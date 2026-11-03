"use client";

import { useId, useLayoutEffect, useMemo, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import {
  extractMentions,
  filterCandidates,
  findMentionQuery,
  insertMention,
  type MentionCandidate,
  type MentionQuery,
} from "@/lib/mentions";
import { MESSAGE_TEXT_MAX } from "@/lib/types";

export interface MentionAgent extends MentionCandidate {
  /** Secondary text in the autocomplete, for example "anthropic / claude-sonnet-5-5". */
  detail?: string;
}

interface Props {
  /** `mentions` holds the ids of agents whose "@DisplayName" is in the text. */
  onSend: (text: string, mentions: string[]) => void;
  disabled?: boolean;
  sending?: boolean;
  deliveryError?: boolean;
  roomName?: string;
  /** Agents in this room that can be mentioned. */
  agents?: readonly MentionAgent[];
}

const NO_AGENTS: readonly MentionAgent[] = [];
const TO_KEY = "composer-send-to";
/** "none": a note to the room, nobody replies. "all": every agent replies. Else one agent's id. */
export type SendTo = "none" | "all" | string;

/** Who answers by default: the last choice if it still exists, else Claude, else the first agent. */
export function defaultSendTo(agents: readonly MentionAgent[], saved: string | null): SendTo {
  if (saved === "none" || (saved === "all" && agents.length > 1)) return saved;
  if (saved && agents.some((a) => a.id === saved)) return saved;
  const claude = agents.find((a) => a.display_name.toLowerCase().startsWith("claude"));
  return claude?.id ?? agents[0]?.id ?? "none";
}

/** The agents a message goes to: the ones picked under "Send to" plus any @mentioned in the text. */
export function recipients(to: SendTo, agents: readonly MentionAgent[], inText: string[]): string[] {
  const picked = to === "all" ? agents.map((a) => a.id) : to === "none" ? [] : [to];
  return [...new Set([...picked.filter((id) => agents.some((a) => a.id === id)), ...inText])];
}

function readSaved(): string | null {
  try {
    return window.localStorage.getItem(TO_KEY);
  } catch {
    return null;
  }
}

/** Shared by RoomView and delivery integration tests. Retry stays in the outbox. */
export function composerDeliveryState(pending: readonly { status: string }[]) {
  return {
    sending: pending.some((item) => item.status !== "failed"),
    deliveryError: pending.some((item) => item.status === "failed"),
  };
}

/**
 * Enter sends, Shift+Enter inserts a newline. Send is disabled while empty.
 * Typing "@" opens an autocomplete of room agents (arrows, Enter or Tab to pick, Esc to close).
 */
export function Composer({
  onSend,
  disabled,
  sending = false,
  deliveryError = false,
  roomName,
  agents = NO_AGENTS,
}: Props) {
  const [text, setText] = useState("");
  const [query, setQuery] = useState<MentionQuery | null>(null);
  const [active, setActive] = useState(0);
  const [dismissedAt, setDismissedAt] = useState<number | null>(null);
  const [toChoice, setToChoice] = useState<SendTo | null>(null);
  const sendTo =
    toChoice !== null && (toChoice === "none" || toChoice === "all" || agents.some((a) => a.id === toChoice))
      ? toChoice
      : defaultSendTo(agents, typeof window === "undefined" ? null : readSaved());
  function chooseTo(next: SendTo) {
    setToChoice(next);
    try {
      window.localStorage.setItem(TO_KEY, next);
    } catch {
      // Storage may be off; the choice still holds while this page is open.
    }
  }
  const toName =
    sendTo === "all"
      ? "Everyone"
      : sendTo === "none"
        ? null
        : (agents.find((a) => a.id === sendTo)?.display_name ?? null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const pendingCaret = useRef<number | null>(null);
  const hintId = useId();
  const listId = useId();
  const trimmed = text.trim();
  const tooLong = trimmed.length > MESSAGE_TEXT_MAX;
  const canSend = !disabled && trimmed.length > 0 && !tooLong;

  const options = useMemo(
    () => (query && query.start !== dismissedAt ? filterCandidates(agents, query.query) : []),
    [agents, query, dismissedAt],
  );
  const open = options.length > 0;
  const activeIndex = Math.min(active, Math.max(0, options.length - 1));

  useLayoutEffect(() => {
    const caret = pendingCaret.current;
    const el = inputRef.current;
    if (caret === null || !el) return;
    pendingCaret.current = null;
    el.focus();
    el.setSelectionRange(caret, caret);
  }, [text]);

  function updateQuery(value: string, caret: number) {
    const q = findMentionQuery(value, caret);
    setQuery(q);
    if (!q || q.start !== query?.start) {
      setActive(0);
      setDismissedAt(null);
    }
  }

  function pick(agent: MentionAgent) {
    if (!query) return;
    const caret = inputRef.current?.selectionStart ?? text.length;
    const next = insertMention(text, query, caret, agent.display_name);
    pendingCaret.current = next.caret;
    setText(next.text);
    setQuery(null);
    setActive(0);
  }

  function submit() {
    if (!canSend) return;
    onSend(trimmed, recipients(sendTo, agents, extractMentions(trimmed, agents)));
    setText("");
    setQuery(null);
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.nativeEvent.isComposing) return;
    if (open) {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setActive((activeIndex + 1) % options.length);
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setActive((activeIndex - 1 + options.length) % options.length);
        return;
      }
      if (e.key === "Enter" || e.key === "Tab") {
        const agent = options[activeIndex];
        if (agent) {
          e.preventDefault();
          pick(agent);
          return;
        }
      }
      if (e.key === "Escape") {
        e.preventDefault();
        e.stopPropagation();
        setDismissedAt(query?.start ?? null);
        return;
      }
    }
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    submit();
  }

  const optionId = (i: number) => `${listId}-opt-${i}`;

  const toOptions = [
    ...agents.map((a) => ({ id: a.id as SendTo, label: a.display_name })),
    ...(agents.length > 1 ? [{ id: "all" as SendTo, label: "Everyone" }] : []),
    { id: "none" as SendTo, label: "No one (note)" },
  ];
  const status = disabled
    ? "Messaging unavailable."
    : deliveryError
      ? "A message was not sent. Use Retry or Discard on the message above."
      : sending
        ? "Sending…"
        : "";

  return (
    <form
      onSubmit={onSubmit}
      data-state={disabled ? "disabled" : deliveryError ? "error" : sending ? "sending" : "default"}
      className="composer shrink-0 px-3 pb-4 pt-2 sm:px-6 sm:pb-5"
    >
      <label htmlFor="composer-input" className="sr-only">
        {roomName ? `Message #${roomName}` : "Message"}
      </label>
      <div className="relative">
        {open && (
          <ul
            id={listId}
            role="listbox"
            aria-label="Mention an agent"
            data-testid="mention-list"
            className="absolute bottom-full left-0 z-20 mb-1 max-h-56 w-64 overflow-y-auto rounded-md border border-line bg-panel py-1 shadow-lg"
          >
            {options.map((a, i) => (
              <li
                key={a.id}
                id={optionId(i)}
                role="option"
                aria-selected={i === activeIndex}
                data-testid="mention-option"
                onMouseDown={(e) => {
                  e.preventDefault();
                  pick(a);
                }}
                onMouseEnter={() => setActive(i)}
                className={`flex cursor-pointer items-baseline gap-2 px-2 py-1 text-sm ${
                  i === activeIndex ? "bg-accent-soft text-fg" : "hover:bg-panel-2"
                }`}
              >
                <span className="font-medium">@{a.display_name}</span>
                {a.detail && <span className="truncate font-mono text-[10px] text-muted">{a.detail}</span>}
              </li>
            ))}
          </ul>
        )}
        <div className="flex items-end gap-2 rounded-xl border border-line bg-panel p-2.5 focus-within:border-accent focus-within:shadow-[0_0_0_1px_var(--accent)]">
          {agents.length > 0 && (
            <select
              aria-label="Send to"
              data-testid="send-to"
              value={sendTo}
              onChange={(e) => chooseTo(e.target.value)}
              disabled={disabled}
              title="Who answers"
              className="h-10 max-w-[9rem] shrink-0 cursor-pointer rounded-lg bg-panel-2 px-2 text-[13px] font-medium text-muted hover:text-fg"
            >
              {toOptions.map((o) => (
                <option key={o.id} value={o.id} data-testid="send-to-option">
                  {o.id === "none" || o.id === "all" ? o.label : `To ${o.label}`}
                </option>
              ))}
            </select>
          )}
          <textarea
            ref={inputRef}
            id="composer-input"
            data-testid="composer-input"
            rows={1}
            value={text}
            onChange={(e) => {
              setText(e.target.value);
              updateQuery(e.target.value, e.target.selectionStart ?? e.target.value.length);
            }}
            onSelect={(e) => {
              const el = e.currentTarget;
              if (el.selectionStart === el.selectionEnd) updateQuery(el.value, el.selectionStart);
            }}
            onBlur={() => setQuery(null)}
            onKeyDown={onKeyDown}
            disabled={disabled}
            placeholder={
              toName ? `Message ${toName === "Everyone" ? "everyone" : toName}…` : "Write a note to the room…"
            }
            aria-describedby={hintId}
            aria-autocomplete="list"
            aria-controls={open ? listId : undefined}
            aria-activedescendant={open ? optionId(activeIndex) : undefined}
            className="max-h-48 min-h-10 min-w-0 flex-1 resize-none bg-transparent px-1 py-[9px] leading-snug placeholder:text-muted focus-visible:outline-none [field-sizing:content]"
          />
          <button
            type="submit"
            data-testid="composer-send"
            disabled={!canSend}
            className="h-10 shrink-0 rounded-lg bg-accent px-[18px] text-sm font-bold text-accent-fg hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
          >
            Send
          </button>
        </div>
      </div>
      <p role="status" aria-atomic="true" className={status ? "mt-2 text-[13px] text-muted" : "sr-only"}>
        {status}
      </p>
      <p id={hintId} className={tooLong ? "mt-2 text-[13px]" : "sr-only"}>
        {tooLong ? (
          <span className="text-danger">
            Message is too long ({trimmed.length.toLocaleString()} of {MESSAGE_TEXT_MAX.toLocaleString()} characters).
          </span>
        ) : (
          `${
            toName ? `${toName === "Everyone" ? "Every agent" : toName} will reply.` : "Nobody replies to a note."
          } Enter to send, Shift+Enter for a new line.`
        )}
      </p>
    </form>
  );
}
