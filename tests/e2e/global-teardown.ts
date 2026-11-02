import { execFileSync } from "node:child_process";
import { existsSync, readFileSync, rmSync } from "node:fs";
import path from "node:path";

// Playwright stops the web server with a signal that can skip its cleanup, so stop the
// throwaway PostgreSQL cluster it recorded (see backend/tests/pg_harness.py).
export default function globalTeardown(): void {
  const marker = path.join(__dirname, ".e2e-pg-root");
  if (!existsSync(marker)) return;
  const root = readFileSync(marker, "utf8").trim();
  const pgCtl = ["17", "16", "15"].map((v) => `/usr/lib/postgresql/${v}/bin/pg_ctl`).find(existsSync);
  if (root.startsWith("/tmp/cc-pg-") && pgCtl) {
    const args = ["-D", path.join(root, "data"), "-m", "immediate", "stop"];
    try {
      if (process.getuid?.() === 0) execFileSync("runuser", ["-u", "postgres", "--", pgCtl, ...args], { stdio: "ignore" });
      else execFileSync(pgCtl, args, { stdio: "ignore" });
    } catch {
      // already stopped
    }
    rmSync(root, { recursive: true, force: true });
  }
  rmSync(marker, { force: true });
}
