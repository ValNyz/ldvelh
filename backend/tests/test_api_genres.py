"""
Integration tests for genre endpoints.
"""

import pytest

from helpers import auth_headers

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_list_genres(client, test_user, seeded_genres):
    resp = await client.get("/api/genres", headers=auth_headers(test_user["token"]))
    assert resp.status_code == 200
    data = resp.json()
    assert "genres" in data
    assert len(data["genres"]) == 4


@pytest.mark.asyncio
async def test_get_genre_by_id(client, test_user, seeded_genres):
    # First list genres to pick a valid ID
    list_resp = await client.get("/api/genres", headers=auth_headers(test_user["token"]))
    genres = list_resp.json()["genres"]
    assert len(genres) > 0

    # Find the sci_fi genre
    sci_fi = next(g for g in genres if g["slug"] == "sci_fi")
    genre_id = sci_fi["id"]

    resp = await client.get(f"/api/genres/{genre_id}", headers=auth_headers(test_user["token"]))
    assert resp.status_code == 200
    data = resp.json()
    assert data["slug"] == "sci_fi"


@pytest.mark.asyncio
async def test_get_genre_not_found(client, test_user):
    fake_id = "00000000-0000-0000-0000-000000000000"
    resp = await client.get(f"/api/genres/{fake_id}", headers=auth_headers(test_user["token"]))
    assert resp.status_code == 404
