"use client";

import { useTheme } from "@/lib/theme";

/** Dark / Light switch. The choice is remembered in this browser. */
export function ThemeToggle() {
  const [theme, setTheme] = useTheme();
  const option = (value: "dark" | "light", label: string) => (
    <button
      type="button"
      data-testid={`theme-${value}`}
      aria-pressed={theme === value}
      onClick={() => setTheme(value)}
      className={`min-h-8 rounded-md px-2.5 text-xs font-semibold ${
        theme === value ? "bg-accent text-accent-fg" : "text-muted hover:text-fg"
      }`}
    >
      {label}
    </button>
  );
  return (
    <div role="group" aria-label="Theme" className="flex shrink-0 gap-0.5 rounded-lg border border-line p-0.5">
      {option("dark", "Dark")}
      {option("light", "Light")}
    </div>
  );
}
