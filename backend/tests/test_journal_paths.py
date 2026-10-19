"""Every world write of a turn is journaled under its turn id: the turn commit, extraction,
the new-cycle hooks and the Director; world generation and the initial Director are not
(#105)."""

import json
from uuid import UUID

from tests.characterization import payloads
from tests.helpers import character_names, extractor_for, narration_with


async def test_every_write_path_of_a_turn_journals_under_it(harness, world_game):
    game_id = UUID(world_game)
    async with harness.pool.acquire() as conn:
        # Outside any turn (not journaled): a stale seed, and the game at the eve of day 12.
        await conn.execute(
            "INSERT INTO narrative_seeds (game_id, cycle, text) VALUES ($1, 1, 'graine')",
            game_id,
        )
        await conn.execute("UPDATE games SET current_cycle = 11 WHERE id = $1", game_id)
        char = await conn.fetchrow(
            "SELECT name FROM characters WHERE game_id = $1 ORDER BY name LIMIT 1",
            game_id,
        )
        last_change = await conn.fetchval(
            "SELECT coalesce(max(id), 0) FROM world_changes"
        )

    harness.llm._responses["resolver"] = payloads.RESOLVER_NEW_CHARACTER
    harness.llm._responses["extract:extract_characters"] = (
        payloads.EXTRACT_CHARACTERS_NEW
    )
    harness.llm._responses["director"] = json.dumps(
        {
            **json.loads(payloads.DIRECTOR),
            "arc_updates": [
                {
                    "action": "create",
                    "title": "Arc du tour",
                    "description": "Né du tour.",
                }
            ],
        }
    )
    harness.llm._responses["narration"] = narration_with(
        day_transition={"new_cycle": 12, "new_date": "Jour 12"},
        entity_reveals=[
            {
                "entity_type": "character",
                "current_name": char["name"],
                "real_name": "Nora Révélée",
            }
        ],
    )
    events = await harness.chat(world_game, "Je dors puis je parle à l'inconnue.")
    await harness.drain()
    assert "done" in harness.summarize(events)

    async with harness.pool.acquire() as conn:
        turn_id = await conn.fetchval(
            "SELECT id FROM turns WHERE game_id = $1 ORDER BY created_at DESC LIMIT 1",
            game_id,
        )
        changes = await conn.fetch(
            "SELECT DISTINCT turn_id, table_name, op FROM world_changes WHERE id > $1",
            last_change,
        )
        log_turns = await conn.fetch(
            "SELECT turn_id FROM extraction_logs WHERE game_id = $1 AND cycle = 12",
            game_id,
        )
        seed = await conn.fetchval(
            "SELECT status FROM narrative_seeds WHERE game_id = $1 AND cycle = 1",
            game_id,
        )

    assert {r["turn_id"] for r in changes} == {turn_id}
    tables = {r["table_name"] for r in changes}
    assert {
        "games",
        "characters",
        "entity_registry",
        "director_plans",
        "narrative_arcs",
    } <= tables
    assert ("characters", "I") in {
        (r["table_name"], r["op"]) for r in changes
    }  # extracted
    assert "extraction_logs" not in tables  # not a world table: not journaled
    assert log_turns and {r["turn_id"] for r in log_turns} == {turn_id}
    assert seed == "archived"
    assert "narrative_seeds" in tables


async def test_world_generation_and_initial_director_are_not_journaled(harness):
    game_id = await harness.create_game("none")
    await harness.init_world(game_id)
    await harness.drain()

    async with harness.pool.acquire() as conn:
        plans = await conn.fetchval(
            "SELECT count(*) FROM director_plans WHERE game_id = $1", game_id
        )
        changes = await conn.fetchval("SELECT count(*) FROM world_changes")
        turns = await conn.fetchval("SELECT count(*) FROM turns")
    assert plans == 1
    assert changes == 0
    assert turns == 0


async def test_extractor_run_without_turn_writes_unjournaled(test_pool, test_user):
    """The unit-test path: an extractor run with no turn writes, but journals nothing."""
    extractor, game_id = await extractor_for(
        test_pool, test_user, {"entities_created": [{"name": "Theta"}]}
    )
    result = await extractor.run("texte", {}, 1)

    assert result["success"] is True
    assert "Theta" in await character_names(test_pool, game_id)
    async with test_pool.acquire() as conn:
        assert await conn.fetchval("SELECT count(*) FROM world_changes") == 0
