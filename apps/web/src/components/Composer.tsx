"use client";

import { useId, useState, type FormEvent, type KeyboardEvent } from "react";
import { MESSAGE_TEXT_MAX } from "@/lib/types";

interface Props {
  onSend: (text: string) => void;
  disabled?: boolean;
  roomName?: string;
}

/** Enter sends, Shift+Enter inserts a newline. Send is disabled while empty. */
export function Composer({ onSend, disabled, roomName }: Props) {
  const [text, setText] = useState("");
  const hintId = useId();
  const trimmed = text.trim();
  const tooLong = trimmed.length > MESSAGE_TEXT_MAX;
  const canSend = !disabled && trimmed.length > 0 && !tooLong;

  function submit() {
    if (!canSend) return;
    onSend(trimmed);
    setText("");
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      submit();
    }
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    submit();
  }

  return (
    <form onSubmit={onSubmit} className="shrink-0 border-t border-line bg-panel px-3 py-2 sm:px-5">
      <label htmlFor="composer-input" className="sr-only">
        {roomName ? `Message #${roomName}` : "Message"}
      </label>
      <div className="flex items-end gap-2 rounded-lg border border-line bg-bg px-2 py-1.5 focus-within:border-accent">
        <textarea
          id="composer-input"
          data-testid="composer-input"
          rows={1}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={onKeyDown}
          disabled={disabled}
          placeholder={roomName ? `Message #${roomName}` : "Message"}
          aria-describedby={hintId}
          className="max-h-48 min-h-[1.75rem] flex-1 resize-none bg-transparent py-1 leading-snug outline-none placeholder:text-muted [field-sizing:content] focus-visible:outline-none"
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
      <p id={hintId} className="mt-1 text-[11px] text-muted">
        {tooLong ? (
          <span className="text-danger">
            Message is too long ({trimmed.length.toLocaleString()} of {MESSAGE_TEXT_MAX.toLocaleString()} characters).
          </span>
        ) : (
          "Enter to send, Shift+Enter for a new line."
        )}
      </p>
    </form>
  );
}
