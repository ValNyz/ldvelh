"""
Integration tests for the full world population pipeline.

Verifies that WorldGeneration data flows correctly from the canonical example
all the way through DB persistence and context builder reconstruction.
"""

import json

import pytest

from prompts.examples import WORLD_GENERATION_EXAMPLE

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _populate_world(test_pool, test_user):
    """Create a game and populate it with the canonical WorldGeneration example.

    Returns (game_id, service, world_gen).
    """
    from schema import WorldGeneration
    from services.game_service import GameService

    world_gen = WorldGeneration.model_validate(json.loads(WORLD_GENERATION_EXAMPLE))
    service = GameService(test_pool)
    user_id = test_user["id"]

    game_id = await service.create_game(user_id)
    await service.process_init(game_id, world_gen)

    return game_id, service, world_gen


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_world_population_pipeline(test_pool, test_user):
    """Populate from canonical example and verify DB state for all entity types."""
    from kg.reader import KnowledgeGraphReader

    game_id, _, _ = await _populate_world(test_pool, test_user)
    reader = KnowledgeGraphReader(test_pool, game_id)

    async with test_pool.acquire() as conn:
        # Protagonist
        protagonist = await reader.get_protagonist(conn)
        assert protagonist is not None
        assert protagonist["name"] == "Valentin"
        assert protagonist["credits"] == 1650

        # Companion
        companion = await reader.get_companion(conn)
        assert companion is not None
        assert companion["name"] == "Célimène"

        # Characters (NPCs — use get_all_characters, known flag may vary by example)
        characters = await reader.get_all_characters(conn)
        assert len(characters) >= 3

        # Locations
        locations = await reader.get_locations(conn)
        assert len(locations) >= 1

        # Organizations
        organizations = await reader.get_organizations(conn)
        assert len(organizations) >= 1
        org_names = [o["name"] for o in organizations]
        assert "Symbiose Tech" in org_names

        # Relations — at least one protagonist ↔ org relation should exist
        relations = await conn.fetch(
            "SELECT * FROM relations WHERE game_id = $1", game_id
        )
        assert len(relations) >= 1

        # Arcs — at least 2 narrative arcs
        arcs = await reader.get_active_arcs(conn)
        assert len(arcs) >= 2

        # Arrival event (chronology entry)
        arrival = await reader.get_arrival_event(conn)
        assert arrival is not None
        # Arrival event is stored as facts/chronology; verify it was populated
        assert "arrival_description" in arrival or "summary" in arrival


@pytest.mark.asyncio
async def test_world_population_then_context(test_pool, test_user):
    """Populate world, then build NarrationContext and verify all fields present."""
    from services.context_builder import ContextBuilder

    game_id, _, world_gen = await _populate_world(test_pool, test_user)
    arrival_loc = world_gen.arrival_event.arrival_location_ref

    builder = ContextBuilder(test_pool, game_id)
    async with test_pool.acquire() as conn:
        ctx = await builder.build(
            conn,
            player_input="Je regarde autour de moi",
            current_cycle=1,
            current_time="08h00",
            current_location_name=arrival_loc,
        )

    # World-level fields
    assert ctx.world_name == "Escale Méridienne"
    assert ctx.world_atmosphere is not None

    # Protagonist
    assert ctx.protagonist is not None
    assert ctx.protagonist.name == "Valentin"
    assert ctx.protagonist.credits == 1650

    # Companion
    assert ctx.companion is not None
    assert ctx.companion.name == "Célimène"

    # Current location resolved
    assert ctx.current_location is not None
    assert ctx.current_location.name == arrival_loc

    # NPCs
    assert len(ctx.all_npcs) >= 3

    # Organizations
    assert len(ctx.organizations) >= 1

    # Arcs
    assert len(ctx.active_arcs) >= 2

    # Inventory
    assert len(ctx.inventory) >= 2
    inv_names = [i.name for i in ctx.inventory]
    assert "Terminal personnel" in inv_names

    # Meta
    assert ctx.current_cycle == 1
    assert ctx.player_input == "Je regarde autour de moi"


@pytest.mark.asyncio
async def test_delete_populated_game(test_pool, test_user):
    """Populate world, then delete game — no FK errors and game is gone."""
    game_id, service, _ = await _populate_world(test_pool, test_user)
    user_id = test_user["id"]

    # Confirm game exists before deletion
    games_before = await service.list_games(user_id)
    assert any(g["id"] == str(game_id) for g in games_before)

    # Delete should not raise (no FK constraint violations)
    await service.delete_game(game_id)

    # Game should no longer appear in the listing
    games_after = await service.list_games(user_id)
    assert not any(g["id"] == str(game_id) for g in games_after)

    # All child rows must have been cascade-deleted
    async with test_pool.acquire() as conn:
        char_count = await conn.fetchval(
            "SELECT COUNT(*) FROM characters WHERE game_id = $1", game_id
        )
        loc_count = await conn.fetchval(
            "SELECT COUNT(*) FROM locations WHERE game_id = $1", game_id
        )
        arc_count = await conn.fetchval(
            "SELECT COUNT(*) FROM narrative_arcs WHERE game_id = $1", game_id
        )

    assert char_count == 0
    assert loc_count == 0
    assert arc_count == 0
