import type { Run } from "@/lib/types";
import { Pill, type PillTone } from "./PanelSection";

const VERDICT: Record<NonNullable<Run["verdict"]>, { label: string; tone: PillTone; title: string }> = {
  done: { label: "Done", tone: "ok", title: "The goal is met or answered." },
  blocked: { label: "Blocked", tone: "danger", title: "It cannot go further; the brief says why." },
  needs_you: { label: "Needs you", tone: "warn", title: "A decision is waiting under Decide." },
};

/** The brief's verdict: Done, Blocked or Needs you. Nothing before a brief exists. */
export function VerdictPill({ verdict }: { verdict: Run["verdict"] }) {
  if (!verdict || !VERDICT[verdict]) return null;
  const v = VERDICT[verdict];
  return (
    <Pill tone={v.tone} testId="verdict" value={verdict} title={v.title}>
      {v.label}
    </Pill>
  );
}
