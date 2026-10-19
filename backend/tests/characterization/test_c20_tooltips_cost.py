"""C-20..C-22: tooltips endpoints (F-23), cost accounting (F-25) and /providers (F-05).

These pin current behavior of paths that had no direct test before the refactor.
"""

import json
from uuid import UUID

from tests.characterization import payloads
from tests.characterization.snapshot import assert_snapshot


async def test_c20_tooltips_annotations_and_entity(harness, world_game):
    # The default narration mentions "Ossek" and "Quart de Cycle": resolve both so spans are stored.
    harness.llm._responses["resolver"] = json.dumps({
        "existing": [
            {"mentions": ["Ossek"], "canonical": "Ossek", "entity_type": "character"},
            {"mentions": ["Quart de Cycle"], "canonical": "Le Quart de Cycle",
             "entity_type": "location"},
        ],
        "new": [],
    })
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
    assert ann["messages"], "resolver mappings must produce stored annotation spans"
    assert found_char.json()["found"] is True
    assert found_loc.json()["found"] is True
    assert missing.json()["found"] is False
    assert_snapshot("c20_tooltips", {
        "annotations": [
            {"sequence_present": m["sequence"] is not None,
             "annotations": [[a["start"], a["end"], a["name"], a["entity_type"]]
                             for a in m["annotations"]]}
            for m in ann["messages"]
        ],
        "character_tooltip": found_char.json(),
        "location_tooltip": found_loc.json(),
        "missing": missing.json(),
    })


def _is_uuid(value) -> bool:
    if not isinstance(value, str):
        return False
    try:
        UUID(value)
    except ValueError:
        return False
    return True


def _stable_meta(meta: dict | None) -> dict | None:
    """Done meta with the turn's random message ids replaced by whether they are UUIDs (#55)."""
    if meta is None:
        return None
    ids = ("user_message_id", "assistant_message_id")
    return {**meta, **{k: _is_uuid(meta.get(k)) for k in ids}}


async def test_c21_cost_recorded_on_message_and_session(harness, world_game, monkeypatch):
    # The scripted model is unpriced; register dynamic pricing (USD per million tokens)
    # so a loss of cost computation changes the snapshot.
    from services import pricing
    monkeypatch.setitem(
        pricing._DYNAMIC_PRICING, "scripted/scripted-model",
        pricing.ModelPricing(input=3.0, output=15.0))
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
        # The done payload sits under "state" (it read done["meta"], always null, before #55).
        "done_state_keys": sorted(done["state"].keys()),
        "meta": _stable_meta(done["state"].get("meta")),
        "message_cost": cost,
        "session_keys": sorted(after.keys()),
        "session_total_grew": after["total_cost_usd"] > before["total_cost_usd"],
        "session_narration_cost_usd": round(
            after["purposes"]["narration"]["cost_usd"]
            - before["purposes"].get("narration", {}).get("cost_usd", 0.0), 6),
        "narration_purpose_tracked": "narration" in after.get("purposes", {}),
    })


async def test_c22_providers_endpoint_without_user_keys(client, test_user, no_api_key):
    """F-05: GET /api/providers with no stored keys (no network, hard-coded Anthropic list only)."""
    from tests.helpers import auth_headers

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
