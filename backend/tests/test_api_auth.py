"""
Integration tests for auth endpoints.
"""

import pytest

from helpers import auth_headers

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_register(client):
    resp = await client.post("/api/auth/register", json={
        "email": "new@test.com",
        "password": "secure123",
        "password_confirm": "secure123",
        "display_name": "New User",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "token" in data
    assert data["user"]["email"] == "new@test.com"
    assert data["user"]["display_name"] == "New User"
    assert data["user"]["email_verified"] is False


@pytest.mark.asyncio
async def test_register_duplicate_email(client, test_user):
    resp = await client.post("/api/auth/register", json={
        "email": "test@example.com",
        "password": "another123",
        "password_confirm": "another123",
    })
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_register_short_password(client):
    resp = await client.post("/api/auth/register", json={
        "email": "short@test.com",
        "password": "12345",
        "password_confirm": "12345",
    })
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_register_password_mismatch(client):
    resp = await client.post("/api/auth/register", json={
        "email": "mismatch@test.com",
        "password": "secure123",
        "password_confirm": "different123",
    })
    assert resp.status_code == 400
    assert "do not match" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_login_by_email(client, test_user):
    resp = await client.post("/api/auth/login", json={
        "identifier": "test@example.com",
        "password": "testpassword",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "token" in data
    assert data["user"]["email"] == "test@example.com"


@pytest.mark.asyncio
async def test_login_by_display_name(client, test_user):
    resp = await client.post("/api/auth/login", json={
        "identifier": "Test User",
        "password": "testpassword",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["user"]["email"] == "test@example.com"


@pytest.mark.asyncio
async def test_login_wrong_password(client, test_user):
    resp = await client.post("/api/auth/login", json={
        "identifier": "test@example.com",
        "password": "wrongpassword",
    })
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_login_unknown_identifier(client):
    resp = await client.post("/api/auth/login", json={
        "identifier": "nobody@test.com",
        "password": "anything",
    })
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_me_authenticated(client, test_user):
    resp = await client.get("/api/auth/me", headers=auth_headers(test_user["token"]))
    assert resp.status_code == 200
    data = resp.json()
    assert data["user"]["email"] == "test@example.com"


@pytest.mark.asyncio
async def test_me_no_token(client):
    resp = await client.get("/api/auth/me")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_me_invalid_token(client):
    resp = await client.get("/api/auth/me", headers=auth_headers("invalid.jwt.token"))
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_change_password(client, test_user):
    # Change password
    resp = await client.post(
        "/api/auth/change-password",
        json={
            "current_password": "testpassword",
            "new_password": "newpassword123",
            "new_password_confirm": "newpassword123",
        },
        headers=auth_headers(test_user["token"]),
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True

    # Verify login with new password works
    login_resp = await client.post("/api/auth/login", json={
        "identifier": "test@example.com",
        "password": "newpassword123",
    })
    assert login_resp.status_code == 200
    assert "token" in login_resp.json()


@pytest.mark.asyncio
async def test_update_display_name(client, test_user):
    resp = await client.patch(
        "/api/auth/profile",
        json={"display_name": "Updated Name"},
        headers=auth_headers(test_user["token"]),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["user"]["display_name"] == "Updated Name"


@pytest.mark.asyncio
async def test_refresh_token(client, test_user):
    resp = await client.post(
        "/api/auth/refresh",
        headers=auth_headers(test_user["token"]),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "token" in data
    assert isinstance(data["token"], str)
    assert len(data["token"]) > 0
