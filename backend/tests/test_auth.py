from __future__ import annotations

from pathlib import Path

import httpx

from tests.conftest import PASSWORD, Server, run_server


async def test_health_needs_no_auth(anon: httpx.AsyncClient) -> None:
    r = await anon.get("/api/health")
    assert r.status_code == 200
    assert r.json()["database"] == "ok"


async def test_unauthenticated_requests_are_rejected(anon: httpx.AsyncClient) -> None:
    for path in ("/api/auth/me", "/api/rooms"):
        r = await anon.get(path)
        assert r.status_code == 401
        assert r.json()["error"]["code"] == "unauthenticated"


async def test_wrong_password(server: Server) -> None:
    async with httpx.AsyncClient(base_url=server.base_url, headers={"X-CC-CSRF": "1"}) as c:
        r = await c.post("/api/auth/login", json={"password": "wrong-password-123"})
        assert r.status_code == 401
        assert r.json()["error"]["code"] == "invalid_credentials"
        assert "cc_session" not in r.cookies


async def test_login_sets_hardened_cookie_and_me_works(server: Server) -> None:
    async with httpx.AsyncClient(base_url=server.base_url, headers={"X-CC-CSRF": "1"}) as c:
        r = await c.post("/api/auth/login", json={"password": PASSWORD})
        assert r.status_code == 200
        assert r.json()["principal"]["kind"] == "owner"
        cookie = r.headers["set-cookie"].lower()
        assert "httponly" in cookie and "samesite=strict" in cookie and "path=/" in cookie
        me = await c.get("/api/auth/me")
        assert me.json()["display_name"] == "Test Owner"


async def test_logout_revokes_session_server_side(server: Server) -> None:
    async with httpx.AsyncClient(base_url=server.base_url, headers={"X-CC-CSRF": "1"}) as c:
        await c.post("/api/auth/login", json={"password": PASSWORD})
        token = c.cookies["cc_session"]
        assert (await c.post("/api/auth/logout")).status_code == 204
    # Replaying the old token must fail even if a client kept it.
    async with httpx.AsyncClient(base_url=server.base_url, cookies={"cc_session": token}) as c2:
        assert (await c2.get("/api/auth/me")).status_code == 401


async def test_csrf_header_required_for_writes(client: httpx.AsyncClient) -> None:
    r = await client.post("/api/rooms", json={"name": "No CSRF"}, headers={"X-CC-CSRF": ""})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "csrf_required"


async def test_foreign_origin_rejected_for_writes(client: httpx.AsyncClient) -> None:
    r = await client.post("/api/rooms", json={"name": "Evil"}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "origin_not_allowed"


async def test_security_headers_present(anon: httpx.AsyncClient) -> None:
    r = await anon.get("/api/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert r.headers["cache-control"] == "no-store"


async def test_login_rate_limit(database_url: str, tmp_path: Path) -> None:
    with run_server(database_url, tmp_path, LOGIN_MAX_FAILURES="3", LOGIN_WINDOW_SECONDS="60") as srv:
        async with httpx.AsyncClient(base_url=srv.base_url, headers={"X-CC-CSRF": "1"}) as c:
            for _ in range(3):
                assert (
                    await c.post("/api/auth/login", json={"password": "nope-nope-nope"})
                ).status_code == 401
            # Even the correct password is refused while blocked.
            r = await c.post("/api/auth/login", json={"password": PASSWORD})
            assert r.status_code == 429
            assert r.json()["error"]["code"] == "rate_limited"
