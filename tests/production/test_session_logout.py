"""The HTTP logout response must clear the cookie and revoke fallback tokens."""

import hashlib
from http.cookies import SimpleCookie

import pytest
from sqlalchemy import select

from backend.models.refresh_token import RefreshToken
from backend.services.auth_service import AuthService
from backend.services.cache_service import CacheService


async def issue(world):
    async with world.sessions() as db:
        return await AuthService(db, CacheService())._issue_tokens(world.users["org_admin"])


@pytest.mark.parametrize("authorization", ["valid", "invalid", "absent"])
async def test_logout_returns_cookie_expiration_on_actual_http_response(world, authorization):
    tokens = await issue(world)
    headers = {"Cookie": "refresh_token=" + tokens["refresh_token"]}
    if authorization != "absent":
        headers["Authorization"] = "Bearer " + (
            tokens["access_token"] if authorization == "valid" else "invalid-local-token"
        )
    response = await world.client.post("/api/v1/auth/logout", headers=headers)
    assert response.status_code == 204
    cookie = SimpleCookie()
    cookie.load(response.headers.get("set-cookie", ""))
    assert "refresh_token" in cookie
    assert cookie["refresh_token"]["max-age"] == "0"
    assert cookie["refresh_token"]["path"] == "/"
    assert cookie["refresh_token"]["httponly"]
    assert cookie["refresh_token"]["secure"]
    assert response.content == b""


@pytest.mark.parametrize("transport", ["cookie", "header"])
async def test_logout_revokes_refresh_from_both_supported_browser_transports(world, transport):
    tokens = await issue(world)
    headers = {"Authorization": "Bearer " + tokens["access_token"]}
    if transport == "cookie":
        headers["Cookie"] = "refresh_token=" + tokens["refresh_token"]
    else:
        headers["X-Refresh-Token"] = tokens["refresh_token"]
    response = await world.client.post("/api/v1/auth/logout", headers=headers)
    assert response.status_code == 204
    async with world.sessions() as db:
        token = await db.scalar(select(RefreshToken).where(
            RefreshToken.token_hash == hashlib.sha256(tokens["refresh_token"].encode()).hexdigest(),
        ))
        revoked = token.revoked
        revoked_at = token.revoked_at
    # Exercise actual endpoints after logout, not just model fields.
    replay = await world.client.post("/api/v1/auth/refresh", headers={"X-Refresh-Token": tokens["refresh_token"]})
    assert replay.status_code == 401
    assert revoked
    assert revoked_at is not None
    me = await world.client.get("/api/v1/auth/me", headers={"Authorization": "Bearer " + tokens["access_token"]})
    assert me.status_code == 401
