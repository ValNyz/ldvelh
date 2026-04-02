"""
Integration tests for user preferences endpoints.
"""

import pytest

from helpers import auth_headers

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_get_empty_preferences(client, test_user):
    resp = await client.get(
        "/api/auth/preferences",
        headers=auth_headers(test_user["token"]),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["preferences"] == {}


@pytest.mark.asyncio
async def test_update_provider_preference(client, test_user):
    resp = await client.patch(
        "/api/auth/preferences",
        json={"preferences": {"default_provider": "mistral"}},
        headers=auth_headers(test_user["token"]),
    )
    assert resp.status_code == 200
    assert resp.json()["preferences"]["default_provider"] == "mistral"


@pytest.mark.asyncio
async def test_store_and_mask_api_key(client, test_user):
    resp = await client.patch(
        "/api/auth/preferences",
        json={"preferences": {"api_keys": {"anthropic": "sk-ant-test-key-1234567890"}}},
        headers=auth_headers(test_user["token"]),
    )
    assert resp.status_code == 200
    masked = resp.json()["preferences"]["api_keys"]["anthropic"]
    # Should be masked, not the raw key
    assert "sk-ant-test-key-1234567890" != masked
    assert "****" in masked or masked.startswith("sk-")


@pytest.mark.asyncio
async def test_remove_api_key(client, test_user):
    # First store a key
    await client.patch(
        "/api/auth/preferences",
        json={"preferences": {"api_keys": {"anthropic": "sk-ant-test-key"}}},
        headers=auth_headers(test_user["token"]),
    )

    # Then remove it
    resp = await client.patch(
        "/api/auth/preferences",
        json={"preferences": {"api_keys": {"anthropic": None}}},
        headers=auth_headers(test_user["token"]),
    )
    assert resp.status_code == 200
    api_keys = resp.json()["preferences"].get("api_keys", {})
    assert "anthropic" not in api_keys


@pytest.mark.asyncio
async def test_invalid_provider(client, test_user):
    resp = await client.patch(
        "/api/auth/preferences",
        json={"preferences": {"api_keys": {"openai": "sk-xxx"}}},
        headers=auth_headers(test_user["token"]),
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_preferences_no_auth(client):
    resp = await client.get("/api/auth/preferences")
    assert resp.status_code == 401
