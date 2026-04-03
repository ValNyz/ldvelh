"""
Integration tests for the full game flow (service layer).
Creates a game, populates the world, processes a narration, then rolls back.
Uses the real test DB — no LLM calls (mocked data).
"""

import json

import pytest

from helpers import auth_headers
from prompts.examples import WORLD_GENERATION_EXAMPLE

pytestmark = pytest.mark.integration


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def world_gen_data():
    """Parsed WorldGeneration dict from the canonical example."""
    return json.loads(WORLD_GENERATION_EXAMPLE)


def _make_narration_output(location: str) -> dict:
    """Build a minimal valid NarrationOutput dict."""
    return {
        "narrative_text": (
            "Valentin pousse la porte du terminal et observe les alentours. "
            "L'air recycl\u00e9 sent le m\u00e9tal et le caf\u00e9 ti\u00e8de. "
            "Quelques voyageurs tra\u00eenent leurs bagages sur le sol us\u00e9."
        ),
        "time": {"new_time": "09h15", "ellipse": False},
        "current_location": location,
        "npcs_present": [],
        "suggested_actions": [
            "Explorer le terminal",
            "Chercher un caf\u00e9",
            "Consulter le panneau d'information",
        ],
        "gauge_deltas": [{"gauge": "energy", "delta": -0.5}],
        "credit_delta": {"amount": -15, "description": "caf\u00e9 au terminal"},
        "inventory_hints": [],
        "entity_reveals": [],
        "info_requests": [],
        "extraction_triggers": [],
    }


# =============================================================================
# WORLD GENERATION FLOW
# =============================================================================


@pytest.mark.asyncio
async def test_create_and_populate_world(client, test_user, test_pool, world_gen_data):
    """Create a game via API, populate the world via service, verify DB state."""
    from schema import WorldGeneration
    from services.game_service import GameService
    from uuid import UUID

    # 1. Create game via API
    resp = await client.post("/api/games", headers=auth_headers(test_user["token"]))
    assert resp.status_code == 200
    game_id = UUID(resp.json()["gameId"])

    # 2. Parse and validate WorldGeneration
    world_gen = WorldGeneration.model_validate(world_gen_data)

    # 3. Populate world via GameService
    service = GameService(test_pool)
    init_result = await service.process_init(game_id, world_gen)

    # 4. Verify init_result shape
    assert init_result["world"]["name"] == "Escale M\u00e9ridienne"
    assert init_result["npc_count"] >= 3
    assert init_result["location_count"] >= 4
    assert init_result["org_count"] >= 1
    assert init_result["arrival"] is not None

    # 5. Verify DB state via load_game_state
    state = await service.load_game_state(game_id)
    assert state["world_created"] is True
    assert state["game"]["name"] is not None

    # 6. Verify entities actually in DB
    async with test_pool.acquire() as conn:
        char_count = await conn.fetchval(
            "SELECT count(*) FROM characters WHERE game_id = $1", game_id
        )
        loc_count = await conn.fetchval(
            "SELECT count(*) FROM locations WHERE game_id = $1", game_id
        )
        org_count = await conn.fetchval(
            "SELECT count(*) FROM organizations WHERE game_id = $1", game_id
        )

    assert char_count >= 3
    assert loc_count >= 4
    assert org_count >= 1


@pytest.mark.asyncio
async def test_load_world_info(client, test_user, test_pool, world_gen_data):
    """After world population, load_world_info returns correct summary."""
    from schema import WorldGeneration
    from services.game_service import GameService
    from uuid import UUID

    resp = await client.post("/api/games", headers=auth_headers(test_user["token"]))
    game_id = UUID(resp.json()["gameId"])

    world_gen = WorldGeneration.model_validate(world_gen_data)
    service = GameService(test_pool)
    await service.process_init(game_id, world_gen)

    world_info = await service.load_world_info(game_id)
    assert world_info is not None
    assert world_info["world"]["name"] == "Escale M\u00e9ridienne"
    assert world_info["npc_count"] >= 3
    assert world_info["ai"]["name"] is not None
    assert world_info["protagonist"]["name"] is not None


# =============================================================================
# NARRATION FLOW
# =============================================================================


@pytest.mark.asyncio
async def test_process_narration_and_save(client, test_user, test_pool, world_gen_data):
    """Process a narration output, save messages, verify state update."""
    from schema import WorldGeneration, NarrationOutput
    from services.game_service import GameService
    from uuid import UUID

    # Setup: create game + populate world
    resp = await client.post("/api/games", headers=auth_headers(test_user["token"]))
    game_id = UUID(resp.json()["gameId"])

    world_gen = WorldGeneration.model_validate(world_gen_data)
    service = GameService(test_pool)
    await service.process_init(game_id, world_gen)

    # Use the arrival location from the example
    arrival_loc = world_gen.arrival_event.arrival_location_ref

    # Build and validate NarrationOutput
    narration_data = _make_narration_output(arrival_loc)
    narration = NarrationOutput.model_validate(narration_data)

    # Process narration (updates cycle, time, location)
    result = await service.process_light(game_id, narration, current_cycle=1)
    assert result["cycle"] == 1  # No day_transition, same cycle
    assert result["time"] == "09h15"
    assert result["location"] == arrival_loc

    # Apply deltas
    delta_result = await service.apply_narrator_deltas(game_id, narration, result["cycle"])
    assert len(delta_result["gauges"]) == 1
    assert delta_result["gauges"][0]["gauge"] == "energy"
    assert delta_result["credits"]["amount"] == -15

    # Save messages
    user_id, assistant_id = await service.save_messages(
        game_id=game_id,
        user_message="Je regarde autour de moi",
        assistant_message=narration.narrative_text,
        cycle=result["cycle"],
        time=result["time"],
        location_ref=result["location"],
    )
    assert user_id is not None
    assert assistant_id is not None

    # Verify messages persisted
    messages = await service.load_chat_messages(game_id)
    assert len(messages) == 2
    assert messages[0]["role"] == "user"
    assert messages[1]["role"] == "assistant"

    # Verify updated game state
    state = await service.load_game_state(game_id)
    assert state["game"]["time"] == "09h15"


@pytest.mark.asyncio
async def test_narrator_deltas_update_stats(
    client, test_user, test_pool, world_gen_data
):
    """Verify that gauge and credit deltas are correctly applied to player stats."""
    from schema import WorldGeneration, NarrationOutput
    from services.game_service import GameService
    from uuid import UUID

    resp = await client.post("/api/games", headers=auth_headers(test_user["token"]))
    game_id = UUID(resp.json()["gameId"])

    world_gen = WorldGeneration.model_validate(world_gen_data)
    service = GameService(test_pool)
    await service.process_init(game_id, world_gen)

    # Record initial state
    state_before = await service.load_game_state(game_id)
    energy_before = state_before["player"]["energy"]
    credits_before = state_before["player"]["credits"]

    # Process narration with deltas
    arrival_loc = world_gen.arrival_event.arrival_location_ref
    narration_data = _make_narration_output(arrival_loc)
    narration = NarrationOutput.model_validate(narration_data)

    await service.process_light(game_id, narration, current_cycle=1)
    await service.apply_narrator_deltas(game_id, narration, 1)

    # Check deltas were applied
    state_after = await service.load_game_state(game_id)
    assert state_after["player"]["energy"] == energy_before - 0.5
    assert state_after["player"]["credits"] == credits_before - 15


# =============================================================================
# ROLLBACK FLOW
# =============================================================================


@pytest.mark.asyncio
async def test_rollback_deletes_messages(
    client, test_user, test_pool, world_gen_data
):
    """Rollback removes messages and rewinds game cycle."""
    from schema import WorldGeneration, NarrationOutput
    from services.game_service import GameService
    from uuid import UUID

    resp = await client.post("/api/games", headers=auth_headers(test_user["token"]))
    game_id = UUID(resp.json()["gameId"])

    world_gen = WorldGeneration.model_validate(world_gen_data)
    service = GameService(test_pool)
    await service.process_init(game_id, world_gen)

    arrival_loc = world_gen.arrival_event.arrival_location_ref

    # Save two rounds of messages
    for i in range(2):
        narration_data = _make_narration_output(arrival_loc)
        narration = NarrationOutput.model_validate(narration_data)
        await service.process_light(game_id, narration, current_cycle=1)
        await service.save_messages(
            game_id=game_id,
            user_message=f"Action {i + 1}",
            assistant_message=narration.narrative_text,
            cycle=1,
            time="09h15",
            location_ref=arrival_loc,
        )

    messages_before = await service.load_chat_messages(game_id)
    assert len(messages_before) == 4  # 2 rounds * 2 messages

    # Rollback from index 2 (keep first round, remove second)
    result = await service.rollback_to_message(game_id, keep_until_index=2)
    assert result["deleted"] == 2

    messages_after = await service.load_chat_messages(game_id)
    assert len(messages_after) == 2


@pytest.mark.asyncio
async def test_rollback_via_api(client, test_user, test_pool, world_gen_data):
    """Rollback via the HTTP endpoint returns updated state."""
    from schema import WorldGeneration, NarrationOutput
    from services.game_service import GameService
    from uuid import UUID

    resp = await client.post("/api/games", headers=auth_headers(test_user["token"]))
    game_id = UUID(resp.json()["gameId"])

    world_gen = WorldGeneration.model_validate(world_gen_data)
    service = GameService(test_pool)
    await service.process_init(game_id, world_gen)

    arrival_loc = world_gen.arrival_event.arrival_location_ref

    # Two rounds of messages
    for i in range(2):
        narration_data = _make_narration_output(arrival_loc)
        narration = NarrationOutput.model_validate(narration_data)
        await service.process_light(game_id, narration, current_cycle=1)
        await service.save_messages(
            game_id=game_id,
            user_message=f"Action {i + 1}",
            assistant_message=narration.narrative_text,
            cycle=1,
            time="09h15",
            location_ref=arrival_loc,
        )

    # Rollback second round via API (keep first 2 messages)
    resp = await client.post(
        f"/api/games/{game_id}/rollback",
        json={"fromIndex": 2},
        headers=auth_headers(test_user["token"]),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["deleted"] == 2
    assert len(data["messages"]) == 2


# =============================================================================
# WORLD DATA ENDPOINTS
# =============================================================================


@pytest.mark.asyncio
async def test_world_data_endpoint(client, test_user, test_pool, world_gen_data):
    """GET /games/{id}/world returns NPCs, locations, organizations."""
    from schema import WorldGeneration
    from services.game_service import GameService
    from uuid import UUID

    resp = await client.post("/api/games", headers=auth_headers(test_user["token"]))
    game_id = UUID(resp.json()["gameId"])

    world_gen = WorldGeneration.model_validate(world_gen_data)
    service = GameService(test_pool)
    await service.process_init(game_id, world_gen)

    resp = await client.get(
        f"/api/games/{game_id}/world",
        headers=auth_headers(test_user["token"]),
    )
    assert resp.status_code == 200
    data = resp.json()

    assert len(data["locations"]) >= 4
    assert len(data["organizations"]) >= 1
    # NPCs may not all be "known" yet, but locations/orgs should exist
    assert "quests" in data
