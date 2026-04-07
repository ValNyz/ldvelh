"""
Integration tests for game CRUD endpoints.
"""

import pytest

from helpers import auth_headers

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_create_game(client, test_user):
    resp = await client.post("/api/games", headers=auth_headers(test_user["token"]))
    assert resp.status_code == 200
    data = resp.json()
    assert "gameId" in data


@pytest.mark.asyncio
async def test_list_games(client, test_user):
    # Create two games
    await client.post("/api/games", headers=auth_headers(test_user["token"]))
    await client.post("/api/games", headers=auth_headers(test_user["token"]))

    resp = await client.get("/api/games", headers=auth_headers(test_user["token"]))
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["games"]) == 2


@pytest.mark.asyncio
async def test_list_games_empty(client, test_user):
    resp = await client.get("/api/games", headers=auth_headers(test_user["token"]))
    assert resp.status_code == 200
    data = resp.json()
    assert data["games"] == []


@pytest.mark.asyncio
async def test_load_game(client, test_user):
    create_resp = await client.post("/api/games", headers=auth_headers(test_user["token"]))
    game_id = create_resp.json()["gameId"]

    resp = await client.get(f"/api/games/{game_id}", headers=auth_headers(test_user["token"]))
    assert resp.status_code == 200
    data = resp.json()
    assert "state" in data
    assert "messages" in data


@pytest.mark.asyncio
async def test_load_game_not_found(client, test_user):
    fake_id = "00000000-0000-0000-0000-000000000000"
    resp = await client.get(f"/api/games/{fake_id}", headers=auth_headers(test_user["token"]))
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_load_game_access_denied(client, test_user, second_user):
    # Create game as test_user
    create_resp = await client.post("/api/games", headers=auth_headers(test_user["token"]))
    game_id = create_resp.json()["gameId"]

    # Try to load as second_user
    resp = await client.get(f"/api/games/{game_id}", headers=auth_headers(second_user["token"]))
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_rename_game(client, test_user):
    create_resp = await client.post("/api/games", headers=auth_headers(test_user["token"]))
    game_id = create_resp.json()["gameId"]

    resp = await client.patch(
        f"/api/games/{game_id}",
        json={"gameId": game_id, "name": "My Adventure"},
        headers=auth_headers(test_user["token"]),
    )
    assert resp.status_code == 200

    # Verify rename persisted
    load_resp = await client.get(f"/api/games/{game_id}", headers=auth_headers(test_user["token"]))
    game_name = load_resp.json()["state"]["game"]["name"]
    assert game_name == "My Adventure"


@pytest.mark.asyncio
async def test_delete_game(client, test_user):
    create_resp = await client.post("/api/games", headers=auth_headers(test_user["token"]))
    game_id = create_resp.json()["gameId"]

    resp = await client.delete(f"/api/games/{game_id}", headers=auth_headers(test_user["token"]))
    assert resp.status_code == 200

    # Verify game no longer listed
    list_resp = await client.get("/api/games", headers=auth_headers(test_user["token"]))
    assert list_resp.json()["games"] == []


@pytest.mark.asyncio
async def test_delete_game_access_denied(client, test_user, second_user):
    create_resp = await client.post("/api/games", headers=auth_headers(test_user["token"]))
    game_id = create_resp.json()["gameId"]

    resp = await client.delete(f"/api/games/{game_id}", headers=auth_headers(second_user["token"]))
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_games_no_auth(client):
    resp = await client.get("/api/games")
    assert resp.status_code == 401

    resp = await client.post("/api/games")
    assert resp.status_code == 401


# =============================================================================
# ENGINE-AWARE GAME CREATION
# =============================================================================


@pytest.mark.asyncio
async def test_create_game_with_engine(client, test_user):
    """POST /games with engine param sets engine on game."""
    resp = await client.post(
        "/api/games",
        json={"engine": "fate_core"},
        headers=auth_headers(test_user["token"]),
    )
    assert resp.status_code == 200
    game_id = resp.json()["gameId"]

    # Load game and verify engine is set
    load_resp = await client.get(
        f"/api/games/{game_id}",
        headers=auth_headers(test_user["token"]),
    )
    assert load_resp.status_code == 200
    state = load_resp.json()["state"]
    assert state["game"]["engine"] == "fate_core"


@pytest.mark.asyncio
async def test_create_game_with_no_body(client, test_user):
    """POST /games with no body still works (defaults to engine=none)."""
    resp = await client.post("/api/games", headers=auth_headers(test_user["token"]))
    assert resp.status_code == 200
    game_id = resp.json()["gameId"]

    load_resp = await client.get(
        f"/api/games/{game_id}",
        headers=auth_headers(test_user["token"]),
    )
    state = load_resp.json()["state"]
    assert state["game"]["engine"] in ("none", None)


@pytest.mark.asyncio
async def test_create_game_with_engine_none(client, test_user):
    """POST /games with engine=none behaves like no engine."""
    resp = await client.post(
        "/api/games",
        json={"engine": "none"},
        headers=auth_headers(test_user["token"]),
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_create_game_engine_in_list(client, test_user):
    """Engine type appears in game list."""
    await client.post(
        "/api/games",
        json={"engine": "d6"},
        headers=auth_headers(test_user["token"]),
    )
    list_resp = await client.get("/api/games", headers=auth_headers(test_user["token"]))
    games = list_resp.json()["games"]
    assert len(games) == 1
    assert games[0]["engine"] == "d6"
