import type { ReactNode } from "react";

export function PanelSection({
  title,
  count,
  action,
  children,
  testId,
}: {
  title: string;
  count?: number;
  action?: ReactNode;
  children: ReactNode;
  testId?: string;
}) {
  return (
    <section data-testid={testId} className="border-b border-line px-3 py-3">
      <h3 className="mb-2 flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wider text-muted">
        {title}
        {count !== undefined && <span className="rounded bg-panel-2 px-1 font-mono">{count}</span>}
        {action && <span className="ml-auto normal-case tracking-normal">{action}</span>}
      </h3>
      {children}
    </section>
  );
}

export type PillTone = "ok" | "warn" | "danger" | "muted" | "accent";

const TONE: Record<PillTone, string> = {
  ok: "bg-ok-soft text-ok",
  warn: "bg-warn-soft text-warn",
  danger: "bg-danger-soft text-danger",
  muted: "bg-panel-2 text-muted",
  accent: "bg-accent-soft text-accent",
};

export function Pill({
  tone,
  children,
  testId,
  value,
  title,
}: {
  tone: PillTone;
  children: ReactNode;
  testId?: string;
  /** Machine-readable value, exposed as data-value. */
  value?: string;
  title?: string;
}) {
  return (
    <span
      data-testid={testId}
      data-value={value}
      data-tone={tone}
      title={title}
      className={`inline-flex shrink-0 items-center gap-1 rounded-full px-1.5 py-px text-[10px] font-medium ${TONE[tone]}`}
    >
      <span aria-hidden="true" className="h-1.5 w-1.5 rounded-full bg-current" />
      {children}
    </span>
  );
}

export function ErrorText({ children }: { children: ReactNode }) {
  return (
    <p role="alert" className="mt-1 text-xs text-danger">
      {children}
    </p>
  );
}
