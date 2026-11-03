"use client";

import { useSyncExternalStore } from "react";

/** The speakers whose color you can pick in Setup > Colors. */
export const SPEAKERS = [
  { key: "claude", label: "Claude" },
  { key: "gpt", label: "ChatGPT" },
  { key: "grok", label: "Grok" },
  { key: "grokbot", label: "Grok Bot" },
  { key: "owner", label: "You" },
] as const;
export type SpeakerKey = (typeof SPEAKERS)[number]["key"];

/** Ready-made colors. Each has a dark and a light shade in tokens.css, so text stays readable. */
export const SWATCHES = [
  { name: "orange", label: "Orange" },
  { name: "green", label: "Green" },
  { name: "blue", label: "Blue" },
  { name: "sky", label: "Sky" },
  { name: "violet", label: "Violet" },
  { name: "pink", label: "Pink" },
  { name: "yellow", label: "Yellow" },
  { name: "red", label: "Red" },
  { name: "teal", label: "Teal" },
  { name: "gray", label: "Gray" },
] as const;
export type SwatchName = (typeof SWATCHES)[number]["name"];

export const DEFAULT_COLORS: Record<SpeakerKey, SwatchName> = {
  claude: "orange",
  gpt: "green",
  grok: "sky",
  grokbot: "violet",
  owner: "blue",
};

export interface SpeakerColors {
  colors: Record<SpeakerKey, SwatchName>;
  locked: Record<SpeakerKey, boolean>;
}

const KEY = "speaker-colors";
const NAMES = new Set<string>(SWATCHES.map((s) => s.name));
const listeners = new Set<() => void>();

function defaults(): SpeakerColors {
  return {
    colors: { ...DEFAULT_COLORS },
    locked: { claude: false, gpt: false, grok: false, grokbot: false, owner: false },
  };
}

/** Reads the saved choices; anything missing or unknown falls back to the default. */
export function loadSpeakerColors(): SpeakerColors {
  const out = defaults();
  try {
    const raw = JSON.parse(window.localStorage.getItem(KEY) ?? "{}") as Partial<SpeakerColors>;
    for (const { key } of SPEAKERS) {
      const c = raw.colors?.[key];
      if (typeof c === "string" && NAMES.has(c)) out.colors[key] = c as SwatchName;
      out.locked[key] = raw.locked?.[key] === true;
    }
  } catch {
    // Storage off or bad data: use the defaults.
  }
  return out;
}

/** Points each speaker's color variable at the chosen swatch (which has its own light shade). */
export function applySpeakerColors(state: SpeakerColors): void {
  const style = document.documentElement.style;
  for (const { key } of SPEAKERS) style.setProperty(`--speaker-${key}`, `var(--swatch-${state.colors[key]})`);
}

let current: SpeakerColors = defaults();

function save(next: SpeakerColors): void {
  current = next;
  try {
    window.localStorage.setItem(KEY, JSON.stringify(next));
  } catch {
    // Storage may be off; the choice still applies until the page reloads.
  }
  applySpeakerColors(next);
  listeners.forEach((l) => l());
}

/** Who already uses a color, so two speakers never look alike. */
export function colorOwner(state: SpeakerColors, color: SwatchName): SpeakerKey | null {
  return SPEAKERS.find((s) => state.colors[s.key] === color)?.key ?? null;
}

/** Picks a color. Refused when the speaker is locked or another speaker has that color. */
export function pickColor(key: SpeakerKey, color: SwatchName): boolean {
  const owner = colorOwner(current, color);
  if (current.locked[key] || (owner && owner !== key)) return false;
  save({ ...current, colors: { ...current.colors, [key]: color } });
  return true;
}

export function setLocked(key: SpeakerKey, locked: boolean): void {
  save({ ...current, locked: { ...current.locked, [key]: locked } });
}

/** Back to the original colors, except for speakers you locked. */
export function resetUnlocked(): void {
  const colors = { ...current.colors };
  for (const { key } of SPEAKERS) if (!current.locked[key]) colors[key] = DEFAULT_COLORS[key];
  // A reset color may clash with a locked one; then keep the current color.
  for (const { key } of SPEAKERS) {
    if (current.locked[key]) continue;
    if (SPEAKERS.some((o) => o.key !== key && colors[o.key] === colors[key])) colors[key] = current.colors[key];
  }
  save({ ...current, colors });
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

const SERVER = defaults();

export function useSpeakerColors(): SpeakerColors {
  return useSyncExternalStore(subscribe, () => current, () => SERVER);
}

/** For tests: start over from what is saved. */
export function reloadSpeakerColors(): void {
  current = loadSpeakerColors();
  applySpeakerColors(current);
  listeners.forEach((l) => l());
}

// Apply the saved colors as soon as the app loads, before the first screen paints.
if (typeof window !== "undefined") reloadSpeakerColors();
