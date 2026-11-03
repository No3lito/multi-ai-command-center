import type { SenderStyle } from "@/lib/senderStyle";

/** A small avatar: the sender's color, initial and shape. */
export function Avatar({ style, size = 28, label }: { style: SenderStyle; size?: number; label: string }) {
  const radius = style.shape === "circle" ? "9999px" : style.shape === "square" ? "6px" : "4px";
  return (
    <span
      data-testid="avatar"
      data-sender={style.key}
      role="img"
      aria-label={label}
      title={label}
      className="inline-flex shrink-0 select-none items-center justify-center font-bold text-[var(--avatar-ink)]"
      style={{
        width: size,
        height: size,
        borderRadius: radius,
        background: style.color,
        fontSize: Math.round(size * 0.45),
        transform: style.shape === "diamond" ? "rotate(45deg) scale(0.82)" : undefined,
      }}
    >
      <span style={{ transform: style.shape === "diamond" ? "rotate(-45deg)" : undefined }}>{style.initial}</span>
    </span>
  );
}
