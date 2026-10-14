"""C-20..C-22: tooltips endpoints (F-23), cost accounting (F-25) and /providers (F-05).

These pin current behavior of paths that had no direct test before the refactor.
"""

import json

from tests.characterization import payloads
from tests.characterization.snapshot import assert_snapshot


async def test_c20_tooltips_annotations_and_entity(harness, world_game):
    harness.llm._responses["resolver"] = payloads.RESOLVER_NEW_CHARACTER
    harness.llm._responses["extract:extract_characters"] = payloads.EXTRACT_CHARACTERS_NEW
    await harness.chat(world_game, "Je regarde autour de moi.")
    await harness.drain()

    r = await harness.client.get(
        "/api/tooltips/annotations", params={"gameId": world_game}, headers=harness.headers)
    assert r.status_code == 200
    ann = r.json()
    async with harness.pool.acquire() as conn:
        char = await conn.fetchval(
            "SELECT name FROM characters WHERE game_id = $1 ORDER BY name LIMIT 1", world_game)
        loc = await conn.fetchval(
            "SELECT name FROM locations WHERE game_id = $1 ORDER BY name LIMIT 1", world_game)
    found_char = await harness.client.get(
        "/api/tooltips/entity",
        params={"gameId": world_game, "name": char, "entityType": "character"},
        headers=harness.headers)
    found_loc = await harness.client.get(
        "/api/tooltips/entity",
        params={"gameId": world_game, "name": loc, "entityType": "location"},
        headers=harness.headers)
    missing = await harness.client.get(
        "/api/tooltips/entity",
        params={"gameId": world_game, "name": "Nobody At All", "entityType": "character"},
        headers=harness.headers)
    assert found_char.json()["found"] is True
    assert found_loc.json()["found"] is True
    assert missing.json()["found"] is False
    assert_snapshot("c20_tooltips", {
        "annotations": [
            {"sequence_present": m["sequence"] is not None,
             "annotations": [[a["start"], a["end"], a["canonical_name"], a["entity_type"]]
                             for a in m["annotations"]]}
            for m in ann["messages"]
        ],
        "character_keys": sorted(found_char.json().keys()),
        "location_keys": sorted(found_loc.json().keys()),
        "missing": missing.json(),
    })


async def test_c21_cost_recorded_on_message_and_session(harness, world_game):
    before = (await harness.client.get("/api/session/cost", headers=harness.headers)).json()
    events = await harness.chat(world_game, "Je regarde autour de moi.")
    await harness.drain()
    after = (await harness.client.get("/api/session/cost", headers=harness.headers)).json()
    done = next(e for e in events if e["type"] == "done")
    async with harness.pool.acquire() as conn:
        raw = await conn.fetchval(
            "SELECT narrator_deltas FROM messages WHERE game_id = $1 AND role = 'assistant' "
            "ORDER BY sequence DESC LIMIT 1", world_game)
    deltas = json.loads(raw) if isinstance(raw, str) else (raw or {})
    cost = deltas.get("cost") or {}
    assert_snapshot("c21_cost", {
        "done_keys": sorted(done.keys()),
        "meta": done.get("meta"),
        "message_cost": cost,
        "session_keys": sorted(after.keys()),
        "session_total_grew": after["total_cost_usd"] > before["total_cost_usd"],
        "narration_purpose_tracked": "narration" in after.get("purposes", {}),
    })


async def test_c22_providers_endpoint_without_user_keys(client, test_user, monkeypatch):
    """F-05: GET /api/providers with no stored keys (no network, hard-coded Anthropic list only)."""
    from api import routes
    from tests.helpers import auth_headers

    async def no_key(pool, user_id, provider_name):
        return None

    monkeypatch.setattr(routes, "_resolve_user_api_key", no_key)
    r = await client.get("/api/providers", headers=auth_headers(test_user["token"]))
    assert r.status_code == 200
    data = r.json()
    providers = data["providers"]
    assert providers["anthropic"]["models"], "Anthropic always lists its hard-coded models"
    assert_snapshot("c22_providers", {
        "top_keys": sorted(data.keys()),
        "providers": sorted(providers.keys()),
        "models_listed": {k: bool(v["models"]) for k, v in sorted(providers.items())},
        "entry_keys": sorted(providers["anthropic"].keys()),
        "model_keys": sorted(providers["anthropic"]["models"][0].keys()),
        "structured_output": {k: v["structured_output"] for k, v in sorted(providers.items())},
    })
