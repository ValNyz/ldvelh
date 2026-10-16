"""POST /api/world/enhance: auth, validation, key lookup, LLM failure."""

import json

import pytest

from helpers import auth_headers
from services import llm_providers
from tests.characterization.scripted_llm import ScriptedLLMProvider, make_provider_class

pytestmark = pytest.mark.integration

WORLD_OUTPUT = {
    "world_config": {"genre": "cyberpunk", "difficulty": "brutal", "duration": "short",
                     "lore": "Mégapole sous la pluie, enrichie."},
    "manual_entities": {"npcs": [{"name": "Rook", "description": "Fixer."}]},
}
CHARACTER_OUTPUT = {
    "character": {"name": "Nyx", "gender": "non-binary", "occupation": "hackeuse",
                  "description": "Yeux chromés."},
    "engine": {},
}


@pytest.fixture
def world_llm(monkeypatch):
    provider = ScriptedLLMProvider({"world_enhance": json.dumps(WORLD_OUTPUT)})
    monkeypatch.setitem(llm_providers._CLASSES, "anthropic", make_provider_class(provider))

    async def _fake_key(pool, user_id, provider_name):
        return "test-api-key"

    from api import routes
    monkeypatch.setattr(routes, "_resolve_user_api_key", _fake_key)
    return provider


def _body(**over):
    body = {"scope": "world", "engine": "none", "provider": "anthropic",
            "current": {"world_config": {"genre": "sci_fi", "hardcore": True,
                                         "lore": "Cyberpunk sous la pluie"}}}
    body.update(over)
    return body


async def test_enhance_fills_the_form(client, test_user, seeded_genres, world_llm):
    resp = await client.post("/api/world/enhance", json=_body(),
                             headers=auth_headers(test_user["token"]))
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["world_config"]["genre"] == "cyberpunk"
    assert data["world_config"]["lore"] == "Mégapole sous la pluie, enrichie."
    assert data["world_config"]["hardcore"] is True  # kept from the form
    assert data["manual_entities"]["npcs"][0]["name"] == "Rook"
    assert "character_data" not in data
    assert world_llm.purposes() == ["world_enhance"]


async def test_enhance_character_scope(client, test_user, seeded_genres, world_llm):
    world_llm._responses["world_enhance"] = json.dumps(CHARACTER_OUTPUT)
    body = _body(scope="character", current={"world_config": {"genre": "cyberpunk"},
                                             "character_data": {"description": "hackeuse"}})
    resp = await client.post("/api/world/enhance", json=body,
                             headers=auth_headers(test_user["token"]))
    assert resp.status_code == 200, resp.text
    assert resp.json()["character_data"]["name"] == "Nyx"
    assert "world_config" not in resp.json()


async def test_enhance_with_empty_text_invents(client, test_user, seeded_genres, world_llm):
    world_llm._responses["world_enhance"] = json.dumps(CHARACTER_OUTPUT)
    resp = await client.post("/api/world/enhance", headers=auth_headers(test_user["token"]),
                             json=_body(scope="character", current={"character_data": {}}))
    assert resp.status_code == 200, resp.text
    assert resp.json()["character_data"]["name"] == "Nyx"
    assert world_llm.purposes() == ["world_enhance"]


@pytest.mark.parametrize("current", [
    {"world_config": {"lore": "x" * 50_000}},
    {"manual_entities": {"npcs": [{"name": f"P{i}", "description": ""} for i in range(500)]}},
])
async def test_enhance_rejects_oversized_input(client, test_user, world_llm, current):
    resp = await client.post("/api/world/enhance", headers=auth_headers(test_user["token"]),
                             json=_body(current=current))
    assert resp.status_code == 422
    assert world_llm.calls == []


async def test_enhance_requires_auth(client):
    resp = await client.post("/api/world/enhance", json=_body())
    assert resp.status_code == 401


async def test_enhance_rejects_unknown_scope_engine_and_provider(client, test_user, world_llm):
    h = auth_headers(test_user["token"])
    assert (await client.post("/api/world/enhance", json=_body(engine="gurps"), headers=h)).status_code == 400
    assert (await client.post("/api/world/enhance", json=_body(provider="nope"), headers=h)).status_code == 400
    assert (await client.post("/api/world/enhance", json=_body(scope="lore"), headers=h)).status_code == 400
    assert world_llm.calls == []


async def test_enhance_without_api_key(client, test_user, seeded_genres, world_llm, monkeypatch):
    from api import routes

    async def _no_key(pool, user_id, provider_name):
        return None

    monkeypatch.setattr(routes, "_resolve_user_api_key", _no_key)
    resp = await client.post("/api/world/enhance", json=_body(),
                             headers=auth_headers(test_user["token"]))
    assert resp.status_code == 400
    assert "Aucune clé API" in resp.json()["detail"]
    assert world_llm.calls == []


async def test_enhance_llm_garbage_gives_502(client, test_user, seeded_genres, world_llm):
    world_llm._responses["world_enhance"] = "pas du JSON"
    resp = await client.post("/api/world/enhance", json=_body(),
                             headers=auth_headers(test_user["token"]))
    assert resp.status_code == 502
