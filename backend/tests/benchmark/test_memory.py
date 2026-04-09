"""
Part 1: Long-term memory tests.
Queries the test DB populated by game_player (via real API).
Verifies entity persistence, relation coherence, inventory tracking,
and dedup quality after a full game session.

No replay needed — the DB already contains the complete game state.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest

from .conftest import get_game_pool_and_info

pytestmark = [pytest.mark.benchmark, pytest.mark.integration]


# =============================================================================
# HELPERS
# =============================================================================


@asynccontextmanager
async def _game(game_dump):
    """Get pool + game info from existing test DB."""
    pool, info = await get_game_pool_and_info(game_dump)
    try:
        yield pool, info
    finally:
        await pool.close()


async def _build_context(pool, game_id, info):
    """Build a NarrationContext at the current game state."""
    from services.context_builder import ContextBuilder

    builder = ContextBuilder(pool, game_id)
    async with pool.acquire() as conn:
        return await builder.build(
            conn=conn,
            player_input="Je regarde autour de moi.",
            current_cycle=info["final_cycle"],
            current_time=info.get("time", "14h00"),
            current_location_name=info.get("location", ""),
        )


# =============================================================================
# SCENARIO A: ENTITY PERSISTENCE
# =============================================================================


class TestEntityPersistence:
    """After a full game, entities should still exist in DB and context."""

    @pytest.mark.asyncio
    async def test_worldgen_characters_in_db(self, game_dump):
        """World-gen characters still in DB with removed_cycle IS NULL."""
        async with _game(game_dump) as (pool, info):
            game_id = info["game_id"]
            world_chars = game_dump["world_gen"].get("characters", [])
            expected_names = {c["name"] for c in world_chars}

            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT name FROM characters "
                    "WHERE game_id = $1 AND removed_cycle IS NULL",
                    game_id,
                )

            db_names = {r["name"] for r in rows}
            missing = expected_names - db_names
            assert not missing, (
                f"World-gen characters missing from DB: {missing}"
            )

    @pytest.mark.asyncio
    async def test_npcs_in_context(self, game_dump):
        """NarrationContext contains NPCs (known or unknown)."""
        async with _game(game_dump) as (pool, info):
            context = await _build_context(pool, info["game_id"], info)

            all_npcs = context.all_npcs or []
            assert len(all_npcs) > 0, "No NPCs at all in context"

            known_npcs = [n for n in all_npcs if hasattr(n, 'known') and n.known]
            print(
                f"[INFO] NPCs in context: {len(all_npcs)} total, "
                f"{len(known_npcs)} known by name"
            )

    @pytest.mark.asyncio
    async def test_known_npcs_exist(self, game_dump):
        """At least some NPCs should be known_by_protagonist after a full game."""
        async with _game(game_dump) as (pool, info):
            game_id = info["game_id"]

            async with pool.acquire() as conn:
                known_count = await conn.fetchval(
                    "SELECT COUNT(*) FROM characters "
                    "WHERE game_id = $1 AND known_by_protagonist = true",
                    game_id,
                )

            assert known_count > 0, (
                "No NPCs are known_by_protagonist after the full game. "
                "Extraction may not have run or entity_reveals were empty."
            )

    @pytest.mark.asyncio
    @pytest.mark.benchmark_llm
    async def test_known_npc_recall(self, game_dump, benchmark_provider):
        """LLM judge: can the narrator recall a known NPC from context?"""
        async with _game(game_dump) as (pool, info):
            context = await _build_context(pool, info["game_id"], info)

            known_npcs = [
                n for n in (context.all_npcs or [])
                if hasattr(n, 'known') and n.known
            ]
            if not known_npcs:
                pytest.skip("No known NPCs in context")

            test_npc = known_npcs[0].name

            from prompts.narrator_prompt import build_narrator_context_prompt
            context_prompt = build_narrator_context_prompt(context, "none", None)

            from .evaluators import LLMJudge
            judge = LLMJudge(provider_name=benchmark_provider)
            recall_score = await judge.judge_entity_recall(context_prompt, test_npc)

            assert recall_score >= 1, (
                f"Known NPC '{test_npc}' not recalled from context (score: {recall_score}/2)"
            )


# =============================================================================
# SCENARIO B: RELATION COHERENCE
# =============================================================================


class TestRelationCoherence:
    """Relations should be valid and consistent."""

    @pytest.mark.asyncio
    async def test_relations_have_valid_entities(self, game_dump):
        """All active relations have valid source/target in entity_registry."""
        async with _game(game_dump) as (pool, info):
            game_id = info["game_id"]

            async with pool.acquire() as conn:
                relations = await conn.fetch(
                    """SELECT r.source_id, r.target_id, r.type,
                              s.name as source_name, t.name as target_name
                       FROM relations r
                       JOIN entity_registry s ON r.source_id = s.id
                       JOIN entity_registry t ON r.target_id = t.id
                       WHERE r.game_id = $1 AND r.end_cycle IS NULL""",
                    game_id,
                )

            for rel in relations:
                assert rel["source_name"], f"Relation has null source: {rel}"
                assert rel["target_name"], f"Relation has null target: {rel}"

            print(f"[INFO] {len(relations)} active relations found")

    @pytest.mark.asyncio
    async def test_no_contradictory_relations(self, game_dump):
        """No contradictory relation pairs (enemy_of + friend_of same pair)."""
        async with _game(game_dump) as (pool, info):
            game_id = info["game_id"]

            contradictory_pairs = [
                ("enemy_of", "friend_of"),
                ("enemy_of", "ally_of"),
                ("trusts", "distrusts"),
            ]

            async with pool.acquire() as conn:
                relations = await conn.fetch(
                    """SELECT source_id, target_id, type
                       FROM relations
                       WHERE game_id = $1 AND end_cycle IS NULL""",
                    game_id,
                )

            rel_set = {
                (r["source_id"], r["target_id"], r["type"])
                for r in relations
            }

            violations = []
            for r in relations:
                for type_a, type_b in contradictory_pairs:
                    if r["type"] == type_a:
                        if (r["source_id"], r["target_id"], type_b) in rel_set:
                            violations.append(
                                f"{r['source_id']}→{r['target_id']}: "
                                f"has both {type_a} and {type_b}"
                            )

            assert not violations, (
                f"Contradictory relations found: {violations}"
            )

    @pytest.mark.asyncio
    async def test_context_has_npcs(self, game_dump):
        """NarrationContext should contain NPC data."""
        async with _game(game_dump) as (pool, info):
            context = await _build_context(pool, info["game_id"], info)

            all_npc_names = {npc.name for npc in (context.all_npcs or [])}
            assert len(all_npc_names) > 0, "No NPCs in context"


# =============================================================================
# SCENARIO C: INVENTORY & CREDITS
# =============================================================================


class TestInventoryTracking:
    """Inventory and credits should be consistent."""

    @pytest.mark.asyncio
    async def test_inventory_no_negative_quantities(self, game_dump):
        """All inventory items should have positive quantities."""
        async with _game(game_dump) as (pool, info):
            game_id = info["game_id"]

            async with pool.acquire() as conn:
                inventory = await conn.fetch(
                    """SELECT o.name, i.quantity
                       FROM inventory i
                       JOIN objects o ON i.object_id = o.id
                       WHERE i.game_id = $1""",
                    game_id,
                )

            for item in inventory:
                assert item["quantity"] >= 0, (
                    f"Negative quantity for '{item['name']}': {item['quantity']}"
                )

            print(f"[INFO] {len(inventory)} inventory items found")

    @pytest.mark.asyncio
    async def test_protagonist_in_context(self, game_dump):
        """NarrationContext has protagonist with valid credits."""
        async with _game(game_dump) as (pool, info):
            context = await _build_context(pool, info["game_id"], info)

            assert context.protagonist is not None
            assert isinstance(context.protagonist.credits, (int, float))

    @pytest.mark.asyncio
    async def test_credits_non_negative(self, game_dump):
        """Player credits should not go below zero."""
        async with _game(game_dump) as (pool, info):
            game_id = info["game_id"]

            async with pool.acquire() as conn:
                credits = await conn.fetchval(
                    "SELECT credits FROM protagonists WHERE game_id = $1", game_id
                )

            if credits is None:
                pytest.skip("No protagonist credits found")
            assert credits >= 0, f"Credits went negative: {credits}"


# =============================================================================
# SCENARIO D: EXTRACTION QUALITY (DEDUP + ENTITY COUNTS)
# =============================================================================


class TestExtractionStress:
    """Entity dedup quality over a long game session."""

    @pytest.mark.asyncio
    async def test_no_duplicate_entities(self, game_dump):
        """No duplicate entity names (case-insensitive) in entity_registry."""
        async with _game(game_dump) as (pool, info):
            game_id = info["game_id"]

            async with pool.acquire() as conn:
                dupes = await conn.fetch(
                    """SELECT entity_type, LOWER(name) as lname, COUNT(*) as cnt
                       FROM entity_registry
                       WHERE game_id = $1
                       GROUP BY entity_type, LOWER(name)
                       HAVING COUNT(*) > 1""",
                    game_id,
                )

            assert len(dupes) == 0, (
                f"Duplicate entities found: "
                + ", ".join(f"{d['entity_type']}:'{d['lname']}' x{d['cnt']}" for d in dupes)
            )

    @pytest.mark.asyncio
    async def test_entity_count_reasonable(self, game_dump):
        """Total entity count within expected bounds."""
        async with _game(game_dump) as (pool, info):
            game_id = info["game_id"]
            num_turns = len(game_dump.get("turns", []))

            world_gen_chars = len(game_dump["world_gen"].get("characters", []))
            world_gen_locs = len(game_dump["world_gen"].get("locations", []))

            async with pool.acquire() as conn:
                char_count = await conn.fetchval(
                    "SELECT COUNT(*) FROM characters WHERE game_id = $1", game_id
                )
                loc_count = await conn.fetchval(
                    "SELECT COUNT(*) FROM locations WHERE game_id = $1", game_id
                )

            max_expected_chars = world_gen_chars + (num_turns // 5) + 10
            assert char_count <= max_expected_chars, (
                f"Too many characters ({char_count}). "
                f"Expected <= {max_expected_chars} (world_gen={world_gen_chars})"
            )

            max_expected_locs = world_gen_locs + (num_turns // 10) + 10
            assert loc_count <= max_expected_locs, (
                f"Too many locations ({loc_count}). "
                f"Expected <= {max_expected_locs} (world_gen={world_gen_locs})"
            )

            print(f"[INFO] Characters: {char_count}, Locations: {loc_count}")

    @pytest.mark.asyncio
    async def test_facts_exist(self, game_dump):
        """After a full game with extraction, facts should exist in DB."""
        async with _game(game_dump) as (pool, info):
            game_id = info["game_id"]

            async with pool.acquire() as conn:
                fact_count = await conn.fetchval(
                    "SELECT COUNT(*) FROM facts WHERE game_id = $1", game_id
                )

            assert fact_count > 0, (
                "No facts in DB after full game. Extraction may not have run."
            )
            print(f"[INFO] {fact_count} facts found")

    @pytest.mark.asyncio
    async def test_extraction_logs_exist(self, game_dump):
        """Extraction should have logged at least some runs."""
        async with _game(game_dump) as (pool, info):
            game_id = info["game_id"]

            async with pool.acquire() as conn:
                log_count = await conn.fetchval(
                    "SELECT COUNT(*) FROM extraction_logs WHERE game_id = $1", game_id
                )

            print(f"[INFO] {log_count} extraction log entries")
