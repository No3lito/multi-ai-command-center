"use client";

import {
  SPEAKERS,
  SWATCHES,
  colorOwner,
  pickColor,
  resetUnlocked,
  setLocked,
  useSpeakerColors,
} from "@/lib/speakerColors";
import { PanelSection } from "./PanelSection";

function LockIcon({ open }: { open: boolean }) {
  return (
    <svg aria-hidden="true" width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6">
      <rect x="3" y="7" width="10" height="7" rx="1.5" />
      <path d={open ? "M5.5 7V5a2.5 2.5 0 0 1 4.9-.7" : "M5.5 7V5a2.5 2.5 0 0 1 5 0v2"} />
    </svg>
  );
}

/** Pick each speaker's color. Lock a speaker so its color can't be changed by mistake. */
export function SpeakerColorsPanel() {
  const state = useSpeakerColors();
  const label = (key: string) => SPEAKERS.find((s) => s.key === key)?.label ?? key;

  return (
    <PanelSection
      title="Colors"
      testId="speaker-colors"
      action={
        <button
          type="button"
          data-testid="colors-reset"
          onClick={resetUnlocked}
          className="text-xs text-muted underline hover:text-fg"
        >
          Reset unlocked
        </button>
      }
    >
      <ul className="flex flex-col gap-3">
        {SPEAKERS.map(({ key, label: name }) => {
          const locked = state.locked[key];
          const chosen = state.colors[key];
          return (
            <li key={key} data-testid="speaker-color-row" data-speaker={key} data-locked={locked}>
              <div className="mb-1.5 flex items-center gap-2">
                <span
                  aria-hidden="true"
                  className="h-3 w-3 rounded-full"
                  style={{ background: `var(--swatch-${chosen})` }}
                />
                <span className="text-sm font-semibold" style={{ color: `var(--swatch-${chosen})` }}>
                  {name}
                </span>
                <span className="text-xs text-muted">{SWATCHES.find((s) => s.name === chosen)?.label}</span>
                <button
                  type="button"
                  data-testid="speaker-color-lock"
                  aria-pressed={locked}
                  aria-label={locked ? `Unlock ${name}'s color` : `Lock ${name}'s color`}
                  onClick={() => setLocked(key, !locked)}
                  className={`ml-auto flex min-h-7 items-center gap-1 rounded-md border px-2 text-xs font-medium ${
                    locked ? "border-accent bg-accent-soft text-fg" : "border-line text-muted hover:text-fg"
                  }`}
                >
                  <LockIcon open={!locked} />
                  {locked ? "Locked" : "Lock"}
                </button>
              </div>
              {!locked && (
                <div role="radiogroup" aria-label={`${name}'s color`} className="flex flex-wrap gap-1.5">
                  {SWATCHES.map((s) => {
                    const owner = colorOwner(state, s.name);
                    const taken = owner !== null && owner !== key;
                    const selected = chosen === s.name;
                    return (
                      <button
                        key={s.name}
                        type="button"
                        role="radio"
                        aria-checked={selected}
                        aria-label={taken ? `${s.label} (used by ${label(owner)})` : s.label}
                        title={taken ? `${s.label}: used by ${label(owner)}` : s.label}
                        data-testid="speaker-color-swatch"
                        data-color={s.name}
                        disabled={taken}
                        onClick={() => pickColor(key, s.name)}
                        className={`h-7 w-7 rounded-full border-2 disabled:cursor-not-allowed disabled:opacity-25 ${
                          selected ? "border-fg" : "border-transparent"
                        }`}
                        style={{ background: `var(--swatch-${s.name})` }}
                      />
                    );
                  })}
                </div>
              )}
            </li>
          );
        })}
      </ul>
      <p className="mt-3 text-xs text-muted">Saved in this browser. A color used by someone else is grayed out.</p>
    </PanelSection>
  );
}
