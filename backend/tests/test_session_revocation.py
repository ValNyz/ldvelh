"""Revocable JWT sessions: token_version, absolute lifetime, password change, logout (#83)."""

from datetime import datetime, timedelta, timezone

import jwt
import pytest

from config import get_settings
from helpers import auth_headers
from services.auth_service import create_token, decode_token

pytestmark = pytest.mark.integration

NEW_PASSWORD = {"current_password": "testpassword", "new_password": "newpassword123",
                "new_password_confirm": "newpassword123"}


async def _me(client, token):
    return await client.get("/api/auth/me", headers=auth_headers(token))


def _forge(**claims):
    settings = get_settings()
    return jwt.encode(claims, settings.jwt_secret, algorithm=settings.jwt_algorithm)


@pytest.mark.asyncio
async def test_a_token_issued_before_a_password_change_is_rejected(client, test_user):
    old = test_user["token"]
    resp = await client.post("/api/auth/change-password", json=NEW_PASSWORD,
                             headers=auth_headers(old))
    assert resp.status_code == 200
    new = resp.json()["token"]

    assert (await _me(client, old)).status_code == 401
    assert (await client.post("/api/auth/refresh", headers=auth_headers(old))).status_code == 401
    assert (await _me(client, new)).status_code == 200  # this device stays signed in


@pytest.mark.asyncio
async def test_logout_invalidates_the_current_token(client, test_user):
    token = test_user["token"]
    assert (await client.post("/api/auth/logout", headers=auth_headers(token))).status_code == 200
    assert (await _me(client, token)).status_code == 401
    assert (await client.post("/api/auth/refresh", headers=auth_headers(token))).status_code == 401
    login = await client.post("/api/auth/login", json={"identifier": "test@example.com",
                                                       "password": "testpassword"})
    assert (await _me(client, login.json()["token"])).status_code == 200


@pytest.mark.asyncio
async def test_refresh_keeps_the_session_start(client, test_user):
    first = decode_token(test_user["token"])
    resp = await client.post("/api/auth/refresh", headers=auth_headers(test_user["token"]))
    assert resp.status_code == 200
    assert decode_token(resp.json()["token"])["orig_iat"] == first["orig_iat"]


@pytest.mark.asyncio
async def test_refresh_beyond_the_absolute_lifetime_fails(client, test_user):
    max_hours = get_settings().jwt_session_max_hours
    start = datetime.now(timezone.utc) - timedelta(hours=max_hours, minutes=1)
    # Even a token whose own exp is still in the future is refused once the session is over.
    token = _forge(sub=str(test_user["id"]), email=test_user["email"], ver=0,
                   iat=datetime.now(timezone.utc), orig_iat=int(start.timestamp()),
                   exp=datetime.now(timezone.utc) + timedelta(hours=1))
    assert (await client.post("/api/auth/refresh", headers=auth_headers(token))).status_code == 401
    assert (await _me(client, token)).status_code == 401


def test_refreshed_tokens_never_outlive_the_session():
    max_hours = get_settings().jwt_session_max_hours
    start = datetime.now(timezone.utc) - timedelta(hours=max_hours - 1)
    payload = decode_token(create_token("00000000-0000-0000-0000-000000000001", "a@b.c",
                                        version=0, session_start=start))
    assert payload["exp"] <= int(start.timestamp()) + max_hours * 3600


@pytest.mark.asyncio
async def test_a_token_without_version_or_session_start_is_rejected(client, test_user):
    exp = datetime.now(timezone.utc) + timedelta(hours=1)
    legacy = _forge(sub=str(test_user["id"]), email=test_user["email"], exp=exp)
    assert (await _me(client, legacy)).status_code == 401
