import { defineConfig } from "@playwright/test";

const PORT = 8765;

export default defineConfig({
  testDir: ".",
  timeout: 60_000,
  fullyParallel: false,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    // Uses the locally installed Google Chrome; set PW_CHANNEL="" to use Playwright's bundled Chromium.
    channel: process.env.PW_CHANNEL ?? "chrome",
    trace: "retain-on-failure",
  },
  webServer: {
    command: `cd ../../backend && uv run python scripts/e2e_server.py --port ${PORT}`,
    url: `http://127.0.0.1:${PORT}/api/health`,
    timeout: 90_000,
    reuseExistingServer: false,
    stdout: "pipe",
    stderr: "pipe",
  },
});
