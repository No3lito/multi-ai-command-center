import { formatCount, formatUsd } from "@/lib/format";
import type { Usage } from "@/lib/types";
import { PanelSection } from "./PanelSection";

interface Props {
  usage: Usage | null;
  error: string | null;
}

/** Instance-wide live spend against the cap. Simulated calls are listed apart and never count as spend. */
export function UsagePanel({ usage, error }: Props) {
  return (
    <PanelSection title="Usage and cost" testId="usage-panel">
      {!usage ? (
        error ? (
          <p role="alert" className="text-xs text-danger">
            {error}
          </p>
        ) : (
          <p className="text-xs text-muted">Loading...</p>
        )
      ) : (
        <UsageBody usage={usage} />
      )}
      {usage && error && <p className="mt-1 text-[10px] text-danger">Last refresh failed: {error}</p>}
    </PanelSection>
  );
}

function UsageBody({ usage }: { usage: Usage }) {
  const pct = usage.cap_usd > 0 ? Math.min(100, ((usage.spent_usd + usage.reserved_usd) / usage.cap_usd) * 100) : 0;
  const spentPct = usage.cap_usd > 0 ? Math.min(100, (usage.spent_usd / usage.cap_usd) * 100) : 0;
  const tone = pct >= 90 ? "bg-danger" : pct >= 70 ? "bg-warn" : "bg-accent";
  const real = usage.by_provider.filter((r) => !r.simulated);
  const simulatedRows = usage.by_provider.filter((r) => r.simulated);

  return (
    <div className="space-y-2">
      <div>
        <p className="flex items-baseline gap-1">
          <span className="text-[11px] text-muted">Live spend</span>
          <span data-testid="usage-spent" className="ml-auto font-mono font-semibold">
            {formatUsd(usage.spent_usd)}
          </span>
          <span className="text-[11px] text-muted">of</span>
          <span data-testid="usage-cap" className="font-mono">
            {formatUsd(usage.cap_usd)}
          </span>
        </p>
        <div
          role="progressbar"
          aria-label="Live spend against the cap"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={Math.round(spentPct)}
          className="relative mt-1 h-1.5 overflow-hidden rounded-full bg-panel-2"
        >
          <div className={`absolute inset-y-0 left-0 opacity-40 ${tone}`} style={{ width: `${pct}%` }} />
          <div className={`absolute inset-y-0 left-0 ${tone}`} style={{ width: `${spentPct}%` }} />
        </div>
        <dl className="mt-1 grid grid-cols-[auto_1fr] gap-x-3 font-mono text-[10px] text-muted">
          <dt>remaining</dt>
          <dd data-testid="usage-remaining" className="text-fg">
            {formatUsd(usage.remaining_usd)}
          </dd>
          <dt>reserved</dt>
          <dd data-testid="usage-reserved" className="text-fg">
            {formatUsd(usage.reserved_usd)}
          </dd>
        </dl>
      </div>

      <div>
        <h4 className="mb-0.5 text-[10px] font-semibold uppercase tracking-wider text-muted">Real API usage</h4>
        {real.length === 0 ? (
          <p className="text-[11px] text-muted">No real API calls yet.</p>
        ) : (
          <table data-testid="usage-table" className="w-full table-fixed font-mono text-[10px]">
            <thead className="text-muted">
              <tr>
                <th className="w-[44%] text-left font-normal">model</th>
                <th className="text-right font-normal">calls</th>
                <th className="text-right font-normal">tokens</th>
                <th className="text-right font-normal">cost</th>
              </tr>
            </thead>
            <tbody>
              {real.map((r) => (
                <tr key={`${r.provider}/${r.model}`} data-testid="usage-row">
                  <td className="truncate" title={`${r.provider} / ${r.model}`}>
                    <span className="text-muted">{r.provider}/</span>
                    {r.model}
                  </td>
                  <td className="text-right">{formatCount(r.calls)}</td>
                  <td className="text-right" title={`${formatCount(r.input_tokens)} in, ${formatCount(r.output_tokens)} out`}>
                    {formatCount(r.input_tokens + r.output_tokens)}
                  </td>
                  <td className="text-right">{formatUsd(r.cost_usd)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div data-testid="usage-simulated" className="rounded-md border border-dashed border-warn/50 bg-warn-soft/50 px-2 py-1">
        <p className="flex items-baseline gap-1 text-[11px]">
          <span className="font-semibold text-warn">Simulated calls</span>
          <span data-testid="usage-simulated-calls" className="ml-auto font-mono font-semibold">
            {formatCount(usage.simulated_calls)}
          </span>
        </p>
        <p className="text-[10px] text-muted">Local stand-in, not real API usage. Free and not counted toward the cap.</p>
        {simulatedRows.length > 0 && (
          <ul className="mt-0.5 font-mono text-[10px] text-muted">
            {simulatedRows.map((r) => (
              <li key={`${r.provider}/${r.model}`} className="flex gap-2">
                <span className="min-w-0 flex-1 truncate">
                  {r.provider}/{r.model}
                </span>
                <span>{formatCount(r.calls)} calls</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
