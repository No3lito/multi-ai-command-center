import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { senderStyle } from "./senderStyle";

// vitest runs from apps/web; import.meta.url is not a file: URL under jsdom.
const css = readFileSync(resolve(process.cwd(), "src/app/tokens.css"), "utf8");

function section(start: string): string {
  const i = css.indexOf(start);
  expect(i).toBeGreaterThan(-1);
  return css.slice(i, css.indexOf("}", i));
}
const dark = section(":root {");
const light = section(':root[data-theme="light"] {');

function token(block: string, name: string): string {
  const m = new RegExp(`${name}:\\s*(#[0-9a-fA-F]{6})`).exec(block);
  expect(m, name).not.toBeNull();
  return m![1]!;
}

function luminance(hex: string): number {
  const n = parseInt(hex.slice(1), 16);
  const [r, g, b] = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((v) => {
    const c = v / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  }) as [number, number, number];
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
export function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x) as [number, number];
  return (hi + 0.05) / (lo + 0.05);
}

describe("tokens.css", () => {
  it("holds the spec values", () => {
    expect(css).toMatch(/--page-pad: 24px/);
    expect(css).toMatch(/--radius-card: 12px/);
    expect(css).toMatch(/--radius-control: 8px/);
    expect(css).toMatch(/--lh-body: 24px/);
    expect(token(dark, "--bg")).toBe("#0f1115");
    expect(token(light, "--panel-2")).toBe("#f0f2f5");
    expect(token(dark, "--accent")).toBe("#e0679e");
  });

  it("is dark by default and light only when selected explicitly", () => {
    expect(css).not.toContain("prefers-color-scheme");
    expect(dark).toContain("color-scheme: dark");
    expect(token(dark, "--bg")).toBe("#0f1115");
    expect(light).toContain("color-scheme: light");
    expect(token(light, "--bg")).toBe("#f6f7f9");
  });

  it("switches the sidebar at 768px (md), not lg", () => {
    const sidebar = readFileSync(resolve(process.cwd(), "src/components/Sidebar.tsx"), "utf8");
    const shell = readFileSync(resolve(process.cwd(), "src/components/Shell.tsx"), "utf8");
    expect(sidebar).not.toMatch(/lg:/);
    expect(sidebar).toContain("md:static");
    expect(shell).toContain("md:hidden");
  });

  it("meets contrast for text in both themes", () => {
    for (const theme of [dark, light]) {
      for (const text of ["--text", "--muted"]) {
        for (const surface of ["--bg", "--panel", "--panel-2"]) {
          expect(contrast(token(theme, text), token(theme, surface)), `${text} on ${surface}`).toBeGreaterThanOrEqual(4.5);
        }
      }
    }
  });

  it("keeps the filled accent label readable and accent text readable on light cards", () => {
    expect(contrast(token(dark, "--accent-fg"), token(dark, "--accent"))).toBeGreaterThanOrEqual(4.5);
    expect(contrast(token(light, "--accent-ink"), token(light, "--panel"))).toBeGreaterThanOrEqual(4.5);
  });

  it("keeps agent dots visible against dark cards (3:1)", () => {
    for (const who of ["Claude", "GPT", "Grok"]) {
      const color = senderStyle({ kind: "agent", display_name: who }).color;
      expect(contrast(color, token(dark, "--panel")), who).toBeGreaterThanOrEqual(3);
    }
  });

  it("keeps the accent at least 40 degrees of hue away from every sender color", () => {
    const hue = (hex: string): number | null => {
      const n = parseInt(hex.slice(1), 16);
      const [r, g, b] = [(n >> 16) & 255, (n >> 8) & 255, n & 255];
      const max = Math.max(r, g, b);
      const min = Math.min(r, g, b);
      if (max - min < 30) return null; // greys carry no hue
      const d = max - min;
      const h = max === r ? ((g - b) / d) % 6 : max === g ? (b - r) / d + 2 : (r - g) / d + 4;
      return (h * 60 + 360) % 360;
    };
    const accentHue = hue(token(dark, "--accent"))!;
    const senders = [
      { kind: "agent", display_name: "Claude" },
      { kind: "agent", display_name: "GPT" },
      { kind: "agent", display_name: "Grok" },
      { kind: "external", display_name: "Grok Bot" },
      { kind: "system", display_name: "Coordinator" },
      { kind: "owner", display_name: "Noel" },
      { kind: "agent", display_name: "Other" },
    ];
    for (const s of senders) {
      const h = hue(senderStyle(s).color);
      if (h === null) continue;
      const diff = Math.abs(h - accentHue);
      expect(Math.min(diff, 360 - diff), s.display_name).toBeGreaterThanOrEqual(40);
    }
  });

  it("keeps the light accent ink readable on the page background too", () => {
    expect(contrast(token(light, "--accent-ink"), token(light, "--bg"))).toBeGreaterThanOrEqual(4.5);
  });

  it("leaves agent colors unchanged", () => {
    expect(senderStyle({ kind: "agent", display_name: "Claude" }).color).toBe("#E8955A");
    expect(senderStyle({ kind: "agent", display_name: "GPT" }).color).toBe("#34C79A");
    expect(senderStyle({ kind: "agent", display_name: "Grok" }).color).toBe("#A78BFA");
    expect(senderStyle({ kind: "owner", display_name: "Noel" }).color).toBe("#4C9AFF");
  });
});
