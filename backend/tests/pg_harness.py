"""Throwaway PostgreSQL cluster for tests (no Docker needed).

Uses TEST_DATABASE_URL if set. Otherwise starts a temporary cluster with the local
PostgreSQL binaries on a free port and removes it afterwards.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


def _pg_bin() -> Path:
    for candidate in sorted(Path("/usr/lib/postgresql").glob("*/bin"), reverse=True):
        if (candidate / "initdb").exists():
            return candidate
    found = shutil.which("initdb")
    if found:
        return Path(found).parent
    raise RuntimeError("PostgreSQL binaries not found; set TEST_DATABASE_URL instead")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _as_pg_user(cmd: list[str]) -> list[str]:
    # initdb refuses to run as root; drop to the postgres account when needed.
    if os.geteuid() == 0:
        return ["runuser", "-u", "postgres", "--", *cmd]
    return cmd


@contextmanager
def temporary_postgres() -> Iterator[str]:
    url = os.environ.get("TEST_DATABASE_URL")
    if url:
        yield url
        return
    bindir = _pg_bin()
    root = Path(tempfile.mkdtemp(prefix="cc-pg-"))
    data = root / "data"
    if os.geteuid() == 0:
        shutil.chown(root, "postgres", "postgres")
    marker = os.environ.get("CC_PG_ROOT_FILE")
    if marker:
        # Lets an external teardown stop this cluster if our process is killed before cleanup.
        Path(marker).write_text(str(root))
    port = _free_port()
    password = "test-only-password"
    pwfile = root / "pw"
    pwfile.write_text(password)
    if os.geteuid() == 0:
        shutil.chown(pwfile, "postgres", "postgres")
    subprocess.run(
        _as_pg_user(
            [
                str(bindir / "initdb"),
                "-D",
                str(data),
                "-U",
                "cc",
                "--pwfile",
                str(pwfile),
                "-A",
                "scram-sha-256",
                "-E",
                "UTF8",
            ]
        ),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        _as_pg_user(
            [
                str(bindir / "pg_ctl"),
                "-D",
                str(data),
                "-l",
                str(root / "log"),
                "-w",
                "-o",
                f"-p {port} -k {root} -c listen_addresses=127.0.0.1 -c fsync=off",
                "start",
            ]
        ),
        check=True,
        capture_output=True,
    )
    try:
        dsn = f"postgresql://cc:{password}@127.0.0.1:{port}/postgres"
        for _ in range(50):
            ok = subprocess.run(
                [str(bindir / "pg_isready"), "-h", "127.0.0.1", "-p", str(port)], capture_output=True
            )
            if ok.returncode == 0:
                break
            time.sleep(0.1)
        subprocess.run(
            [str(bindir / "psql"), dsn, "-qc", "CREATE DATABASE command_center_test"],
            check=True,
            capture_output=True,
        )
        yield f"postgresql://cc:{password}@127.0.0.1:{port}/command_center_test"
    finally:
        subprocess.run(
            _as_pg_user([str(bindir / "pg_ctl"), "-D", str(data), "-m", "immediate", "stop"]),
            capture_output=True,
        )
        shutil.rmtree(root, ignore_errors=True)
