"""Rate limits over HTTP: auth keyed on the trusted-proxy client IP, /chat per user and IP (#82)."""

import uuid

import pytest

from config import get_settings
from helpers import auth_headers

pytestmark = pytest.mark.integration

LOGIN = {"identifier": "nobody@example.com", "password": "wrong"}


async def _logins(client, forwarded_values):
    statuses = []
    for value in forwarded_values:
        resp = await client.post("/api/auth/login", json=LOGIN,
                                 headers={"X-Forwarded-For": value})
        statuses.append(resp.status_code)
    return statuses, resp


@pytest.mark.asyncio
async def test_spoofed_forwarded_for_does_not_reset_the_login_limit_without_proxy(client):
    statuses, last = await _logins(client, [f"6.6.6.{i}" for i in range(6)])
    assert statuses == [401] * 5 + [429]
    assert last.json() == {"detail": last.json()["detail"], "code": "rate_limited"}
    assert last.json()["detail"].startswith("Trop de requêtes")
    assert last.headers["retry-after"] == "60"


@pytest.mark.asyncio
async def test_spoofed_forwarded_for_does_not_reset_the_login_limit_behind_one_proxy(
        client, monkeypatch):
    monkeypatch.setattr(get_settings(), "trusted_proxy_hops", 1)
    # The client varies the head; the proxy always appends the address it really saw.
    statuses, _ = await _logins(client, [f"6.6.6.{i}, 203.0.113.9" for i in range(6)])
    assert statuses == [401] * 5 + [429]
    other = await client.post("/api/auth/login", json=LOGIN,
                              headers={"X-Forwarded-For": "198.51.100.4"})
    assert other.status_code == 401  # another real client is not throttled


async def _chat(client, token):
    return await client.post("/api/chat", json={"gameId": str(uuid.uuid4()), "message": "Salut"},
                             headers=auth_headers(token))


@pytest.mark.asyncio
async def test_chat_is_rate_limited_per_user_in_french(client, test_user, second_user):
    from api.routes import chat_user_limiter

    for _ in range(chat_user_limiter.max_requests):
        chat_user_limiter.hit(f"user:{test_user['id']}")
    resp = await _chat(client, test_user["token"])
    assert resp.status_code == 429
    assert resp.json()["code"] == "rate_limited"
    assert resp.json()["detail"].startswith("Trop de requêtes")
    # Another player is not throttled (404: the random game does not exist).
    assert (await _chat(client, second_user["token"])).status_code == 404


@pytest.mark.asyncio
async def test_chat_is_rate_limited_per_ip(client, test_user):
    from api.routes import chat_ip_limiter

    for _ in range(chat_ip_limiter.max_requests):
        chat_ip_limiter.hit("127.0.0.1")  # the ASGI test client's address
    resp = await _chat(client, test_user["token"])
    assert resp.status_code == 429
    assert resp.json()["code"] == "rate_limited"


@pytest.mark.asyncio
async def test_resend_verification_is_throttled_per_user(client, test_user):
    statuses = []
    for _ in range(4):
        resp = await client.post("/api/auth/resend-verification",
                                 headers=auth_headers(test_user["token"]))
        statuses.append(resp.status_code)
    assert statuses == [200, 200, 200, 429]
