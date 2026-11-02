"""`command-center` CLI: migrate, serve."""

from __future__ import annotations

import argparse
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]


def migrate() -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    command.upgrade(cfg, "head")


def main() -> None:
    parser = argparse.ArgumentParser(prog="command-center")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("migrate", help="apply database migrations")
    serve = sub.add_parser("serve", help="run the API and dashboard")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    if args.cmd == "migrate":
        migrate()
    elif args.cmd == "serve":
        import uvicorn

        uvicorn.run("command_center.main:app", host=args.host, port=args.port, proxy_headers=False)


if __name__ == "__main__":
    main()
