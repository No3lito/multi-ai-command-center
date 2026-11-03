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

/**
 * Enter sends, Shift+Enter inserts a newline. Send is disabled while empty.
 * Typing "@" opens an autocomplete of room agents (arrows, Enter or Tab to pick, Esc to close).
 */
export function Composer({ onSend, disabled, sending = false, deliveryError = false, roomName, agents = NO_AGENTS }: Props) {
  const [text, setText] = useState("");
  const [query, setQuery] = useState<MentionQuery | null>(null);
  const [active, setActive] = useState(0);
  const [dismissedAt, setDismissedAt] = useState<number | null>(null);
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
    onSend(trimmed, extractMentions(trimmed, agents));
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

  return (
    <form
      onSubmit={onSubmit}
      data-state={disabled ? "disabled" : deliveryError ? "error" : sending ? "sending" : "default"}
      className="composer shrink-0 border-t border-line bg-panel px-3 py-4 sm:px-5"
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
        <div className="flex items-end gap-2 rounded-lg border border-line bg-bg px-2 py-1.5 focus-within:border-accent">
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
            placeholder="Message the team…"
            aria-describedby={hintId}
            aria-autocomplete="list"
            aria-controls={open ? listId : undefined}
            aria-activedescendant={open ? optionId(activeIndex) : undefined}
            className="max-h-48 min-h-[1.75rem] min-w-0 flex-1 resize-none bg-transparent py-1 leading-snug placeholder:text-muted [field-sizing:content]"
          />
          <button
            type="submit"
            data-testid="composer-send"
            disabled={!canSend}
            className="rounded-md bg-accent px-3 py-1 text-sm font-medium text-accent-fg hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
          >
            Send
          </button>
        </div>
      </div>
      <p role="status" className="mt-2 text-[13px] text-muted">
        {disabled ? "Messaging unavailable." : deliveryError
          ? "A message was not sent. Use Retry or Discard on the message above."
          : sending ? "Sending…" : ""}
      </p>
      <p id={hintId} className="mt-1 text-[13px] text-muted">
        {tooLong ? (
          <span className="text-danger">
            Message is too long ({trimmed.length.toLocaleString()} of {MESSAGE_TEXT_MAX.toLocaleString()} characters).
          </span>
        ) : (
          "Message the team… (Enter to send, Shift+Enter for new line). Mention an agent with @ to ask it directly."
        )}
      </p>
    </form>
  );
}
