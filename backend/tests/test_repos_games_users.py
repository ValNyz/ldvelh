"""Repos for users and games: API key lookup, genre by slug, game genre/duration."""

from uuid import UUID

import pytest

from helpers import auth_headers
from repos import games as games_repo
from repos import users as users_repo

pytestmark = pytest.mark.integration


async def _create_game(client, test_user) -> UUID:
    resp = await client.post("/api/games", headers=auth_headers(test_user["token"]))
    return UUID(resp.json()["gameId"])


@pytest.mark.asyncio
async def test_get_user_api_key_decrypts_the_stored_key(client, test_user, test_pool):
    resp = await client.patch(
        "/api/auth/preferences",
        json={"preferences": {"api_keys": {"anthropic": "sk-ant-test-key-1234567890"}}},
        headers=auth_headers(test_user["token"]),
    )
    assert resp.status_code == 200
    async with test_pool.acquire() as conn:
        key = await users_repo.get_user_api_key(conn, test_user["id"], "anthropic")
        missing = await users_repo.get_user_api_key(conn, test_user["id"], "mistral")
    assert key == "sk-ant-test-key-1234567890"
    assert missing is None


@pytest.mark.asyncio
async def test_genre_by_slug_and_game_genre(client, test_user, test_pool, seeded_genres):
    game_id = await _create_game(client, test_user)
    async with test_pool.acquire() as conn:
        genre = await games_repo.get_genre_by_slug(conn, "sci_fi")
        assert genre is not None and genre["id"] is not None
        assert await games_repo.get_genre_by_slug(conn, "nope") is None
        await games_repo.set_game_genre(conn, game_id, genre["id"])
        assert await conn.fetchval("SELECT genre_id FROM games WHERE id = $1", game_id) == genre["id"]


@pytest.mark.asyncio
async def test_set_game_duration(client, test_user, test_pool):
    game_id = await _create_game(client, test_user)
    async with test_pool.acquire() as conn:
        await games_repo.set_game_duration(conn, game_id, "short")
        assert await conn.fetchval("SELECT game_duration FROM games WHERE id = $1", game_id) == "short"
