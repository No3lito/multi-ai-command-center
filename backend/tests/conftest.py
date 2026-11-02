"""Test fixtures: a real PostgreSQL database and a real uvicorn server process."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest

from tests.pg_harness import create_database, temporary_postgres

BACKEND = Path(__file__).resolve().parents[1]
PASSWORD = "correct-horse-battery-staple"


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    with temporary_postgres() as url:
        env = dict(os.environ, DATABASE_URL=url)
        subprocess.run(
            [sys.executable, "-m", "command_center.cli", "migrate"],
            cwd=BACKEND,
            env=env,
            check=True,
            capture_output=True,
        )
        yield url


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@dataclass
class Server:
    base_url: str
    origin: str
    proc: subprocess.Popen[bytes]
    log_path: Path

    @property
    def ws_base(self) -> str:
        return self.base_url.replace("http://", "ws://", 1)

    def logs(self) -> str:
        return self.log_path.read_text(errors="ignore")


@contextmanager
def run_server(database_url: str, tmp_path: Path, **extra_env: str) -> Iterator[Server]:
    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    log_path = tmp_path / f"server-{port}.log"
    env = dict(
        os.environ,
        DATABASE_URL=database_url,
        OWNER_PASSWORD=PASSWORD,
        OWNER_DISPLAY_NAME="Test Owner",
        ALLOWED_ORIGINS=base,
        WS_HEARTBEAT_SECONDS="1",
        WEB_DIST=str(tmp_path / "no-web-build"),
        **extra_env,
    )
    with log_path.open("wb") as log:
        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "command_center.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--no-proxy-headers",
            ],
            cwd=BACKEND,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
    server = Server(base, base, proc, log_path)
    try:
        deadline = time.monotonic() + 20
        while True:
            if proc.poll() is not None:
                raise RuntimeError("server exited early:\n" + server.logs())
            try:
                if httpx.get(f"{base}/api/health", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            if time.monotonic() > deadline:
                raise RuntimeError("server did not become healthy:\n" + server.logs())
            time.sleep(0.2)
        yield server
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


@pytest.fixture(scope="session")
def server(database_url: str, tmp_path_factory: pytest.TempPathFactory) -> Iterator[Server]:
    with run_server(database_url, tmp_path_factory.mktemp("srv")) as srv:
        yield srv


@pytest.fixture
async def client(server: Server) -> AsyncIterator[httpx.AsyncClient]:
    """Logged-in client that behaves like the dashboard (CSRF header, same origin)."""
    async with httpx.AsyncClient(
        base_url=server.base_url, headers={"X-CC-CSRF": "1", "Origin": server.origin}
    ) as c:
        r = await c.post("/api/auth/login", json={"password": PASSWORD})
        assert r.status_code == 200, r.text
        yield c


@pytest.fixture
async def anon(server: Server) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(base_url=server.base_url) as c:
        yield c


def session_cookie(c: httpx.AsyncClient) -> str:
    value = c.cookies.get("cc_session")
    assert value
    return value


@pytest.fixture
def fresh_database_url(database_url: str) -> str:
    """An isolated, migrated database, for servers running in a different mode."""
    url = create_database(database_url, f"cc_{uuid.uuid4().hex[:12]}")
    subprocess.run(
        [sys.executable, "-m", "command_center.cli", "migrate"],
        cwd=BACKEND,
        env=dict(os.environ, DATABASE_URL=url),
        check=True,
        capture_output=True,
    )
    return url


@contextmanager
def run_fake_providers(delay: float = 0.0, reply_suffix: str = "") -> Iterator[str]:
    port = _free_port()
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "tests.fake_providers",
            "--port",
            str(port),
            "--delay",
            str(delay),
            "--reply-suffix",
            reply_suffix,
        ],
        cwd=BACKEND,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 15
        while True:
            try:
                if httpx.get(f"{base}/health", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            if time.monotonic() > deadline or proc.poll() is not None:
                raise RuntimeError("fake provider server did not start")
            time.sleep(0.1)
        yield base
    finally:
        proc.terminate()
        proc.wait(timeout=10)
