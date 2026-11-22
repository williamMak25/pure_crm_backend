from __future__ import annotations

from typing import TYPE_CHECKING

from tests.conftest import ADMIN, SALES

if TYPE_CHECKING:
    from litestar import Litestar
    from litestar.testing import AsyncTestClient


async def login(client: AsyncTestClient[Litestar], creds: tuple[str, str]) -> dict:
    response = await client.post("/api/auth/login", json={"email": creds[0], "password": creds[1]})
    assert response.status_code == 200, response.text
    return response.json()


async def test_health(client: AsyncTestClient[Litestar]) -> None:
    response = await client.get("/health")
    assert response.json() == {"status": "ok", "database": "online"}


async def test_protected_routes_need_a_session(client: AsyncTestClient[Litestar]) -> None:
    response = await client.get("/api/me")
    assert response.status_code == 401
    assert "message" in response.json()


async def test_wrong_password_and_unknown_email_look_the_same(client: AsyncTestClient[Litestar]) -> None:
    wrong = await client.post("/api/auth/login", json={"email": ADMIN[0], "password": "nope"})
    unknown = await client.post("/api/auth/login", json={"email": "ghost@test.local", "password": "nope"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["message"] == unknown.json()["message"]


async def test_login_sets_httponly_cookies_and_returns_user(client: AsyncTestClient[Litestar]) -> None:
    response = await client.post("/api/auth/login", json={"email": ADMIN[0].upper(), "password": ADMIN[1]})
    assert response.status_code == 200
    cookies = response.headers.get_list("set-cookie")
    assert any(c.startswith("access_token=") and "HttpOnly" in c for c in cookies)
    assert any(c.startswith("refresh_token=") and "Path=/api/auth" in c for c in cookies)
    assert "authorization" not in response.headers
    body = response.json()
    assert body["email"] == ADMIN[0]
    assert body["isSuperuser"] is True

    me = await client.get("/api/me")
    assert me.status_code == 200
    assert me.json()["id"] == body["id"]


async def test_refresh_rotates_and_detects_reuse(client: AsyncTestClient[Litestar]) -> None:
    await login(client, ADMIN)
    first = client.cookies.get("refresh_token")

    rotated = await client.post("/api/auth/refresh")
    assert rotated.status_code == 200
    second = client.cookies.get("refresh_token")
    assert second and second != first

    # someone replays the old token: the whole family is revoked, including the new one
    client.cookies.set("refresh_token", first, path="/api/auth")
    assert (await client.post("/api/auth/refresh")).status_code == 401
    client.cookies.set("refresh_token", second, path="/api/auth")
    assert (await client.post("/api/auth/refresh")).status_code == 401


async def test_logout_revokes_refresh_token(client: AsyncTestClient[Litestar]) -> None:
    await login(client, ADMIN)
    token = client.cookies.get("refresh_token")
    assert (await client.post("/api/auth/logout")).status_code == 200
    client.cookies.set("refresh_token", token, path="/api/auth")
    assert (await client.post("/api/auth/refresh")).status_code == 401


async def test_businesses_follow_membership(client: AsyncTestClient[Litestar]) -> None:
    await login(client, ADMIN)
    assert {b["name"] for b in (await client.get("/api/businesses")).json()} == {
        "PURE Education",
        "Anime House",
        "GPM",
    }
    client.cookies.clear()
    await login(client, SALES)
    assert [b["name"] for b in (await client.get("/api/businesses")).json()] == ["PURE Education"]


async def test_permission_guard(client: AsyncTestClient[Litestar]) -> None:
    me = await login(client, SALES)
    assert "hr" not in me["permissions"]
    denied = await client.get("/api/_test/hr")
    assert denied.status_code == 403
    assert "message" in denied.json()

    client.cookies.clear()
    await login(client, ADMIN)
    assert (await client.get("/api/_test/hr")).json() == {"ok": "hr"}


async def test_validation_errors_use_message_shape(client: AsyncTestClient[Litestar]) -> None:
    response = await client.post("/api/auth/login", json={"email": "x"})
    assert response.status_code == 400
    body = response.json()
    assert body["message"]
    assert body["errors"]
