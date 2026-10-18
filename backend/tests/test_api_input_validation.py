"""Bad client input answers 4xx with a French message that never echoes the input (#91)."""

import re

import pytest

from helpers import auth_headers

pytestmark = pytest.mark.integration

# Marker put in every rejected value: it must never come back in the body.
SECRET = "ZZSECRETZZ"


def _assert_french_no_echo(resp, status=422):
    assert resp.status_code == status, resp.text
    detail = resp.json()["detail"]
    assert isinstance(detail, str)
    assert SECRET not in resp.text
    assert re.search(r"[éèàêç]|invalide|trop|obligatoire|requête", detail, re.I), detail


async def _new_game(client, user):
    resp = await client.post("/api/games", headers=auth_headers(user["token"]))
    return resp.json()["gameId"]


@pytest.mark.asyncio
async def test_rollback_bad_message_id(client, test_user):
    game_id = await _new_game(client, test_user)
    resp = await client.post(
        f"/api/games/{game_id}/rollback", json={"messageId": SECRET},
        headers=auth_headers(test_user["token"]))
    _assert_french_no_echo(resp)


@pytest.mark.asyncio
async def test_rename_too_long(client, test_user):
    game_id = await _new_game(client, test_user)
    resp = await client.patch(
        f"/api/games/{game_id}", json={"name": SECRET + "x" * 300},
        headers=auth_headers(test_user["token"]))
    _assert_french_no_echo(resp)


@pytest.mark.asyncio
async def test_rename_blank(client, test_user):
    game_id = await _new_game(client, test_user)
    resp = await client.patch(
        f"/api/games/{game_id}", json={"name": "   "},
        headers=auth_headers(test_user["token"]))
    _assert_french_no_echo(resp)


@pytest.mark.asyncio
async def test_create_game_unknown_engine_rejected_and_not_stored(client, test_user):
    resp = await client.post(
        "/api/games", json={"engine": SECRET},
        headers=auth_headers(test_user["token"]))
    _assert_french_no_echo(resp)
    listing = await client.get("/api/games", headers=auth_headers(test_user["token"]))
    assert listing.json()["games"] == []


@pytest.mark.asyncio
async def test_create_game_valid_engine_still_works(client, test_user):
    resp = await client.post(
        "/api/games", json={"engine": "fate_core"},
        headers=auth_headers(test_user["token"]))
    assert resp.status_code == 200
    game_id = resp.json()["gameId"]
    load = await client.get(f"/api/games/{game_id}", headers=auth_headers(test_user["token"]))
    assert load.status_code == 200


def _register(**over):
    body = {"email": "ok@test.com", "password": "secure123", "password_confirm": "secure123"}
    body.update(over)
    return body


@pytest.mark.asyncio
async def test_register_bad_email(client):
    resp = await client.post("/api/auth/register", json=_register(email=SECRET))
    _assert_french_no_echo(resp)


@pytest.mark.asyncio
async def test_register_display_name_too_long(client):
    resp = await client.post(
        "/api/auth/register", json=_register(display_name=SECRET + "x" * 100))
    _assert_french_no_echo(resp)


@pytest.mark.asyncio
async def test_preferences_api_keys_not_a_dict(client, test_user):
    resp = await client.patch(
        "/api/auth/preferences", json={"preferences": {"api_keys": [SECRET]}},
        headers=auth_headers(test_user["token"]))
    _assert_french_no_echo(resp)


@pytest.mark.asyncio
async def test_preferences_api_key_too_long(client, test_user):
    resp = await client.patch(
        "/api/auth/preferences",
        json={"preferences": {"api_keys": {"anthropic": SECRET + "k" * 600}}},
        headers=auth_headers(test_user["token"]))
    _assert_french_no_echo(resp)


@pytest.mark.asyncio
async def test_preferences_too_large(client, test_user):
    resp = await client.patch(
        "/api/auth/preferences",
        json={"preferences": {"notes": SECRET + "n" * 20_000}},
        headers=auth_headers(test_user["token"]))
    _assert_french_no_echo(resp)
