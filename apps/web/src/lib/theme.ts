"use client";

import { useCallback, useSyncExternalStore } from "react";

export type Theme = "dark" | "light";
const KEY = "command-center-theme";
const listeners = new Set<() => void>();

/** The saved theme (dark when nothing is saved or storage is off). */
export function savedTheme(): Theme {
  try {
    return window.localStorage.getItem(KEY) === "light" ? "light" : "dark";
  } catch {
    return "dark";
  }
}

/** Dark is the stylesheet's default; light sets data-theme="light" on <html>. */
export function applyTheme(theme: Theme): void {
  if (theme === "light") document.documentElement.dataset.theme = "light";
  else delete document.documentElement.dataset.theme;
}

export function setTheme(theme: Theme): void {
  try {
    window.localStorage.setItem(KEY, theme);
  } catch {
    // Storage may be off; the theme still applies until the page reloads.
  }
  applyTheme(theme);
  listeners.forEach((l) => l());
}

function current(): Theme {
  return document.documentElement.dataset.theme === "light" ? "light" : "dark";
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** The current theme and a toggle, shared by every component that shows the switch. */
export function useTheme(): [Theme, (t: Theme) => void] {
  const theme = useSyncExternalStore(subscribe, current, () => "dark" as Theme);
  const set = useCallback((t: Theme) => setTheme(t), []);
  return [theme, set];
}

// Apply the saved choice as soon as the app loads, before the first screen paints.
if (typeof window !== "undefined") applyTheme(savedTheme());
