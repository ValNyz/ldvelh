"""
Fixture loader: replays a game_dump.json into the test database without LLM calls.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path
from uuid import UUID

from schema import WorldGeneration, NarrationOutput
from services.game_service import GameService

logger = logging.getLogger(__name__)


async def replay_game_dump(
    pool,
    dump: dict,
    max_turns: int | None = None,
    user_id: UUID | None = None,
) -> dict:
    """Replay a game dump into the test DB.

    Args:
        pool: asyncpg Pool connected to the test database
        dump: Parsed game_dump.json dict
        max_turns: Stop after this many turns (for depth-parametrized tests)
        user_id: User ID to assign the game to (created if None)

    Returns:
        dict with game_id and final state info
    """
    service = GameService(pool)

    # Create a game
    if user_id is None:
        user_id = await _ensure_test_user(pool)

    game_id = await service.create_game(user_id, engine=dump["metadata"].get("engine"))

    # Parse and populate world
    world_gen = WorldGeneration.model_validate(dump["world_gen"])
    await service.process_init(game_id, world_gen)

    # Replay turns
    turns = dump["turns"]
    if max_turns is not None:
        turns = turns[:max_turns]

    current_cycle = 1
    current_time = "08h00"
    current_location = ""

    total = len(turns)
    t0 = time.perf_counter()

    for i, turn in enumerate(turns):
        narration_data = turn["narration_output"]
        if narration_data is None:
            continue  # Skip failed turns
        narration = NarrationOutput.model_validate(narration_data)

        # Process the narration (updates cycle, time, location)
        result = await service.process_light(game_id, narration, current_cycle)
        current_cycle = result["cycle"]
        if result.get("time"):
            current_time = result["time"]
        if result.get("location"):
            current_location = result["location"]

        # Apply deltas (credits, entity reveals)
        await service.apply_narrator_deltas(game_id, narration, current_cycle)

        # Save messages
        await service.save_messages(
            game_id=game_id,
            user_message=turn["user_message"],
            assistant_message=narration.narrative_text,
            cycle=current_cycle,
            time=result.get("time"),
            location_ref=result.get("location"),
        )

        # Progress indicator every 10 turns
        if (i + 1) % 10 == 0 or (i + 1) == total:
            elapsed = time.perf_counter() - t0
            rate = (i + 1) / elapsed if elapsed > 0 else 0
            pct = 100 * (i + 1) / total
            sys.stderr.write(
                f"\r[REPLAY] {i + 1}/{total} turns ({pct:.0f}%) — {rate:.1f} turns/s"
            )
            sys.stderr.flush()

    elapsed = time.perf_counter() - t0
    sys.stderr.write("\n")
    logger.info(
        f"[FIXTURE] Replayed {total} turns for game {game_id} "
        f"(final cycle: {current_cycle}, {elapsed:.1f}s)"
    )

    return {
        "game_id": game_id,
        "user_id": user_id,
        "final_cycle": current_cycle,
        "turns_replayed": len(turns),
        "time": current_time,
        "location": current_location,
    }


async def get_db_snapshot(pool, game_id: UUID) -> dict:
    """Capture a full DB snapshot for a game.

    Returns a dict with all entity tables and their rows.
    """
    from kg.reader import KnowledgeGraphReader

    reader = KnowledgeGraphReader(pool, game_id)

    async with pool.acquire() as conn:
        characters = await reader.get_all_characters(conn)
        locations = await reader.get_locations(conn)
        organizations = await reader.get_organizations(conn)
        objects = await reader.get_objects(conn)
        relations = await reader.get_relations(conn)
        active_arcs = await reader.get_active_arcs(conn)
        facts = await reader.get_facts(conn)
        inventory = await reader.get_inventory(conn)

        # Entity registry
        entity_registry = await conn.fetch(
            "SELECT id, name, entity_type FROM entity_registry WHERE game_id = $1",
            game_id,
        )

        # Game state
        game_state = await conn.fetchrow(
            "SELECT current_cycle, current_date, current_time, name, engine "
            "FROM games WHERE id = $1",
            game_id,
        )

    return {
        "characters": [dict(r) for r in characters],
        "locations": [dict(r) for r in locations],
        "organizations": [dict(r) for r in organizations],
        "objects": [dict(r) for r in objects],
        "relations": [dict(r) for r in relations],
        "arcs": [dict(r) for r in active_arcs],
        "facts": [dict(r) for r in facts],
        "inventory": [dict(r) for r in inventory],
        "entity_registry": [dict(r) for r in entity_registry],
        "game_state": dict(game_state) if game_state else {},
    }


async def _ensure_test_user(pool) -> UUID:
    """Create a test user for benchmark games."""
    from services import auth_service

    async with pool.acquire() as conn:
        # Check if test user exists
        existing = await conn.fetchval(
            "SELECT id FROM users WHERE email = 'benchmark@ldvelh.test'"
        )
        if existing:
            return existing

        # Create one (bypass email verification)
        result = await auth_service.register(
            conn, "benchmark@ldvelh.test", "benchmarkpassword", "Benchmark User"
        )
        return result["id"]
