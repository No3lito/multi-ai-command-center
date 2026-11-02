"""Start a throwaway PostgreSQL plus the app (API and built dashboard) for browser tests.

Usage: uv run python scripts/e2e_server.py --port 8765
Runs until interrupted. Uses tests/pg_harness.py (local PostgreSQL binaries or TEST_DATABASE_URL).
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from tests.pg_harness import temporary_postgres  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    web_dist = BACKEND.parent / "apps" / "web" / "out"
    if not (web_dist / "index.html").exists():
        sys.exit(f"dashboard not built: {web_dist} (run npm run build in apps/web)")
    with temporary_postgres() as url:
        origin = f"http://127.0.0.1:{args.port},http://localhost:{args.port}"
        env = dict(
            os.environ,
            DATABASE_URL=url,
            OWNER_PASSWORD=os.environ.get("E2E_OWNER_PASSWORD", "e2e-owner-password"),
            OWNER_DISPLAY_NAME="E2E Owner",
            ALLOWED_ORIGINS=origin,
            WEB_DIST=str(web_dist),
            WS_HEARTBEAT_SECONDS="2",
            # Browser tests never spend money: agents use labeled simulated stand-ins.
            PROVIDER_MODE=os.environ.get("E2E_PROVIDER_MODE", "simulated"),
        )
        subprocess.run(
            [sys.executable, "-m", "command_center.cli", "migrate"], cwd=BACKEND, env=env, check=True
        )
        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "command_center.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(args.port),
                "--no-proxy-headers",
            ],
            cwd=BACKEND,
            env=env,
        )

        def stop(*_: object) -> None:
            proc.terminate()

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        proc.wait()


if __name__ == "__main__":
    main()
