"""
Part 2b: Narrative quality tests — LLM-as-judge.

Tests the narrator by building the EXACT same input it receives in production:
- System prompt (build_narrator_system_prompt)
- Multi-turn conversation history (build_llm_messages — last 2 cycles)
- Context prompt (build_narrator_context_prompt — world state + player input)

Then judges the response quality with an LLM judge.
"""

from __future__ import annotations

import pytest

from contextlib import asynccontextmanager

from .conftest import get_game_pool_and_info
from .evaluators import LLMJudge

pytestmark = [pytest.mark.benchmark, pytest.mark.benchmark_llm, pytest.mark.integration]


# =============================================================================
# HELPERS
# =============================================================================


@asynccontextmanager
async def _game(game_dump):
    pool, info = await get_game_pool_and_info(game_dump)
    try:
        yield pool, info
    finally:
        await pool.close()


async def _call_narrator_realistically(
    pool, game_id, info, player_input: str, provider_name: str, engine: str = "none"
):
    """Call the narrator exactly like the real API does.

    Builds: system prompt + multi-turn history + context prompt.
    Returns (parsed_json, narrative_text).
    """
    from services.context_builder import ContextBuilder
    from services.game_service import GameService
    from services.llm_providers import get_provider
    from prompts.narrator_prompt import (
        build_narrator_system_prompt,
        build_narrator_context_prompt,
    )
    from utils.json_utils import parse_json_response

    # 1. Build context (same as ContextBuilder.build in real flow)
    builder = ContextBuilder(pool, game_id)
    async with pool.acquire() as conn:
        context = await builder.build(
            conn=conn,
            player_input=player_input,
            current_cycle=info["final_cycle"],
            current_time=info.get("time", "14h00"),
            current_location_name=info.get("location", ""),
        )

    # 2. Build system prompt
    system_prompt = build_narrator_system_prompt(engine)

    # 3. Build context prompt (this is the final user message)
    context_prompt = build_narrator_context_prompt(context, engine, None)

    # 4. Build multi-turn messages (last 2 cycles of conversation history)
    service = GameService(pool)
    llm_messages = await service.build_llm_messages(
        game_id, info["final_cycle"], context_prompt
    )

    # 5. Call the LLM
    provider = get_provider(provider_name)
    result = await provider.complete(
        system_prompt=system_prompt,
        messages=llm_messages,
        temperature=0.8,
        max_tokens=4000,
    )

    if not result or not result.content:
        return None, None

    parsed = parse_json_response(result.content)
    narrative = parsed.get("narrative_text", "") if parsed else ""
    return parsed, narrative


# =============================================================================
# TRACKED NPC RECALL (the core memory test)
# =============================================================================


class TestTrackedNPCRecall:
    """The game introduced an NPC early, then asks about them hundreds of turns later.
    Does the narrator remember them?"""

    @pytest.mark.asyncio
    async def test_tracked_npc_narrator_mentions(self, game_dump, benchmark_provider):
        """When the player asks about the tracked NPC, the narrator should mention them."""
        tracked = game_dump["metadata"].get("tracked_npc")
        if not tracked:
            pytest.skip("No tracked NPC in game dump")

        async with _game(game_dump) as (pool, info):
            _, narrative = await _call_narrator_realistically(
                pool, info["game_id"], info,
                f"Je repense a {tracked}. Est-ce que quelqu'un le connait ici?",
                benchmark_provider,
            )

            if not narrative:
                pytest.skip("Narrator returned empty")

            judge = LLMJudge(provider_name=benchmark_provider)
            mentioned = await judge.judge_yes_no(
                f"Does this narrative mention or reference '{tracked}' "
                f"(by name, description, or role)?",
                narrative,
            )
            assert mentioned, (
                f"Narrator did not mention tracked NPC '{tracked}' when asked.\n"
                f"Narrative: {narrative[:300]}..."
            )

    @pytest.mark.asyncio
    async def test_tracked_npc_context_score(self, game_dump, benchmark_provider):
        """LLM judge: how well is the tracked NPC integrated in the narrator's context?"""
        tracked = game_dump["metadata"].get("tracked_npc")
        if not tracked:
            pytest.skip("No tracked NPC in game dump")

        async with _game(game_dump) as (pool, info):
            _, narrative = await _call_narrator_realistically(
                pool, info["game_id"], info,
                f"Je cherche {tracked} dans la station. Ou est-il?",
                benchmark_provider,
            )

            if not narrative:
                pytest.skip("Narrator returned empty")

            judge = LLMJudge(provider_name=benchmark_provider)
            score = await judge.judge_score(
                f"How well does this narrative handle the player's search for '{tracked}'? "
                f"5 = knows who they are and gives relevant info. "
                f"3 = acknowledges the name but vague. "
                f"0 = ignores or doesn't know who they are.",
                narrative,
            )
            assert score >= 2, (
                f"Tracked NPC '{tracked}' poorly handled (score={score}/5).\n"
                f"Narrative: {narrative[:300]}..."
            )


# =============================================================================
# NPC NAME USAGE
# =============================================================================


class TestNPCNaming:
    """The narrator should use actual NPC names from the KG."""

    @pytest.mark.asyncio
    async def test_narrator_uses_known_npc_names(self, game_dump, benchmark_provider):
        """When NPCs are in context, narrator should use their real names."""
        async with _game(game_dump) as (pool, info):
            game_id = info["game_id"]

            # Get known NPC names from DB
            async with pool.acquire() as conn:
                known = await conn.fetch(
                    "SELECT name FROM characters "
                    "WHERE game_id = $1 AND known_by_protagonist = true LIMIT 5",
                    game_id,
                )
            npc_names = [r["name"] for r in known]
            if len(npc_names) < 1:
                pytest.skip("No known NPCs in DB")

            _, narrative = await _call_narrator_realistically(
                pool, game_id, info,
                "Je demande aux gens autour de moi de se presenter.",
                benchmark_provider,
            )

            if not narrative:
                pytest.skip("Narrator returned empty")

            judge = LLMJudge(provider_name=benchmark_provider)
            result = await judge.judge_names_present(narrative, npc_names)

            assert result["coverage"] >= 0.2, (
                f"Narrator used too few known NPC names: {result['coverage']:.0%}. "
                f"Found: {result['found']}, Missing: {result['missing']}"
            )

    @pytest.mark.asyncio
    async def test_worldgen_npc_named_correctly(self, game_dump, benchmark_provider):
        """Ask about a world-gen NPC by name — narrator should use their exact name."""
        world_chars = game_dump["world_gen"].get("characters", [])
        if not world_chars:
            pytest.skip("No characters in world_gen")

        test_name = world_chars[0]["name"]

        async with _game(game_dump) as (pool, info):
            _, narrative = await _call_narrator_realistically(
                pool, info["game_id"], info,
                f"Parle-moi de {test_name}.",
                benchmark_provider,
            )

            if not narrative:
                pytest.skip("Narrator returned empty")

            judge = LLMJudge(provider_name=benchmark_provider)
            score = await judge.judge_score(
                f"How accurately does this text refer to '{test_name}'? "
                f"5 = uses exact name and relevant details. "
                f"3 = close variant or partial. 0 = wrong name or absent.",
                narrative,
            )
            assert score >= 3, (
                f"World-gen NPC '{test_name}' not named correctly (score={score}/5).\n"
                f"Narrative: {narrative[:300]}..."
            )


# =============================================================================
# LOCATION AWARENESS
# =============================================================================


class TestLocationAwareness:
    """The narrator should know where the player is."""

    @pytest.mark.asyncio
    async def test_narrator_knows_current_location(self, game_dump, benchmark_provider):
        """Narrative should reference the current location."""
        async with _game(game_dump) as (pool, info):
            location = info.get("location", "")
            if not location:
                pytest.skip("No location info")

            _, narrative = await _call_narrator_realistically(
                pool, info["game_id"], info,
                "Je regarde autour de moi et je decris ce que je vois.",
                benchmark_provider,
            )

            if not narrative:
                pytest.skip("Narrator returned empty")

            judge = LLMJudge(provider_name=benchmark_provider)
            aware = await judge.judge_yes_no(
                f"Does this narrative take place in or reference the location '{location}'?",
                narrative,
            )
            assert aware, (
                f"Narrator unaware of current location '{location}'.\n"
                f"Narrative: {narrative[:300]}..."
            )

    @pytest.mark.asyncio
    async def test_location_description_stable(self, game_dump, benchmark_provider):
        """Two narrations at the same location should describe it consistently."""
        async with _game(game_dump) as (pool, info):
            prompt = "Je m'arrete et j'observe les details de cet endroit."
            _, narrative_1 = await _call_narrator_realistically(
                pool, info["game_id"], info, prompt, benchmark_provider,
            )
            _, narrative_2 = await _call_narrator_realistically(
                pool, info["game_id"], info, prompt, benchmark_provider,
            )

            if not narrative_1 or not narrative_2:
                pytest.skip("Narrator returned empty")

            judge = LLMJudge(provider_name=benchmark_provider)
            consistent = await judge.judge_score(
                "How consistent are these two descriptions of the same location? "
                "5 = fully consistent, 3 = mostly consistent, 0 = contradictory.",
                f"Description 1:\n{narrative_1[:500]}\n\nDescription 2:\n{narrative_2[:500]}",
            )
            assert consistent >= 3, (
                f"Location descriptions inconsistent (score={consistent}/5)"
            )


# =============================================================================
# FACT AWARENESS
# =============================================================================


class TestFactAwareness:
    """The narrator should know established facts and reject fabrications."""

    @pytest.mark.asyncio
    async def test_narrator_aligns_with_known_facts(self, game_dump, benchmark_provider):
        """Narrator should align with DB facts when talking about recent events."""
        async with _game(game_dump) as (pool, info):
            game_id = info["game_id"]

            async with pool.acquire() as conn:
                facts = await conn.fetch(
                    "SELECT description FROM facts WHERE game_id = $1 AND importance >= 3 LIMIT 5",
                    game_id,
                )

            if not facts:
                pytest.skip("No important facts in DB")

            fact_text = facts[0]["description"]

            _, narrative = await _call_narrator_realistically(
                pool, game_id, info,
                "Raconte-moi ce qui s'est passe recemment sur la station.",
                benchmark_provider,
            )

            if not narrative:
                pytest.skip("Narrator returned empty")

            judge = LLMJudge(provider_name=benchmark_provider)
            aligned = await judge.judge_score(
                f"Does this narrative align with this established fact: '{fact_text}'? "
                f"5 = explicitly references it. 3 = consistent but doesn't mention it. "
                f"0 = contradicts it.",
                narrative,
            )
            assert aligned >= 2, (
                f"Narrative may contradict fact '{fact_text[:80]}' (score={aligned}/5)"
            )

    @pytest.mark.asyncio
    async def test_narrator_rejects_fabricated_event(self, game_dump, benchmark_provider):
        """Ask about a fake event — narrator should not confirm it."""
        async with _game(game_dump) as (pool, info):
            _, narrative = await _call_narrator_realistically(
                pool, info["game_id"], info,
                "Je me souviens de l'explosion du reacteur 5 la semaine derniere. C'etait terrible.",
                benchmark_provider,
            )

            if not narrative:
                pytest.skip("Narrator returned empty")

            judge = LLMJudge(provider_name=benchmark_provider)
            confirmed = await judge.judge_yes_no(
                "Does this narrative confirm that an explosion of reactor 5 actually happened? "
                "(yes = narrator treats it as a real past event, "
                "no = narrator denies it, is confused, or redirects.)",
                narrative,
            )
            assert not confirmed, (
                f"Narrator confirmed a fabricated event.\n"
                f"Narrative: {narrative[:300]}..."
            )


# =============================================================================
# KG vs NO-KG QUALITY DELTA
# =============================================================================


class TestKGQualityDelta:
    """Narratives with full KG context should be richer than with empty context."""

    @pytest.mark.asyncio
    async def test_kg_produces_richer_narrative(self, game_dump, benchmark_provider):
        """With KG, narrator should produce more specific, detailed narrative."""
        async with _game(game_dump) as (pool, info):
            prompt = "Je traverse la station et j'observe la vie quotidienne."

            # Full KG context (real flow)
            _, narrative_with_kg = await _call_narrator_realistically(
                pool, info["game_id"], info, prompt, benchmark_provider,
            )

            # Minimal context (no KG data)
            from services.llm_providers import get_provider
            from prompts.narrator_prompt import build_narrator_system_prompt
            from schema import NarrationContext, LocationSummary, ProtagonistState
            from services.context_builder import ContextBuilder

            builder = ContextBuilder(pool, info["game_id"])
            async with pool.acquire() as conn:
                full_ctx = await builder.build(
                    conn=conn,
                    player_input=prompt,
                    current_cycle=info["final_cycle"],
                    current_time=info.get("time", "14h00"),
                    current_location_name=info.get("location", ""),
                )

            loc = full_ctx.current_location
            minimal = NarrationContext(
                current_cycle=info["final_cycle"],
                current_date="Mardi 2 janvier 2475",
                current_time="14h00",
                current_location=LocationSummary(
                    name=loc.name if loc else "Station",
                    type=loc.type if loc else "station",
                    sector=loc.sector if loc else "Central",
                    atmosphere=loc.atmosphere if loc else "industrielle",
                ),
                protagonist=ProtagonistState(
                    name=full_ctx.protagonist.name if full_ctx.protagonist else "Valentin",
                    credits=full_ctx.protagonist.credits if full_ctx.protagonist else 1000,
                    hobbies=full_ctx.protagonist.hobbies if full_ctx.protagonist else [],
                ),
                organizations=[],
                all_npcs=[],
                player_input=prompt,
                world_name=full_ctx.world_name or "Station",
                world_atmosphere=full_ctx.world_atmosphere or "industrielle",
            )

            from prompts.narrator_prompt import build_narrator_context_prompt
            minimal_prompt = build_narrator_context_prompt(minimal, "none", None)
            system = build_narrator_system_prompt("none")
            provider = get_provider(benchmark_provider)
            result = await provider.complete(
                system_prompt=system,
                messages=[{"role": "user", "content": minimal_prompt}],
                temperature=0.8,
                max_tokens=4000,
            )
            from utils.json_utils import parse_json_response
            parsed = parse_json_response(result.content) if result and result.content else None
            narrative_without_kg = parsed.get("narrative_text", "") if parsed else ""

            if not narrative_with_kg or not narrative_without_kg:
                pytest.skip("Narrator returned empty")

            judge = LLMJudge(provider_name=benchmark_provider)

            score_prompt = (
                "How specific and grounded is this narrative? "
                "5 = names real characters, references real locations and events. "
                "3 = generic but coherent. 0 = vague or nonsensical."
            )
            with_kg_score = await judge.judge_score(score_prompt, narrative_with_kg)
            without_kg_score = await judge.judge_score(score_prompt, narrative_without_kg)

            assert with_kg_score >= without_kg_score, (
                f"KG context didn't improve narrative: "
                f"with_kg={with_kg_score}/5, without_kg={without_kg_score}/5"
            )

    @pytest.mark.asyncio
    async def test_kg_enables_npc_depth(self, game_dump, benchmark_provider):
        """With KG, narrator should portray NPCs with real personality."""
        async with _game(game_dump) as (pool, info):
            game_id = info["game_id"]

            # Find a known NPC
            async with pool.acquire() as conn:
                npc = await conn.fetchrow(
                    "SELECT name FROM characters "
                    "WHERE game_id = $1 AND known_by_protagonist = true LIMIT 1",
                    game_id,
                )
            if not npc:
                pytest.skip("No known NPCs")

            npc_name = npc["name"]

            _, narrative = await _call_narrator_realistically(
                pool, game_id, info,
                f"Je parle avec {npc_name} de sa vie sur la station.",
                benchmark_provider,
            )

            if not narrative:
                pytest.skip("Narrator returned empty")

            judge = LLMJudge(provider_name=benchmark_provider)
            depth_score = await judge.judge_score(
                f"How well does this narrative portray '{npc_name}' as a unique character "
                f"with personality, history, and specific traits? "
                f"5 = rich characterization. 3 = basic but named. 0 = generic NPC.",
                narrative,
            )
            assert depth_score >= 3, (
                f"NPC '{npc_name}' lacks depth (score={depth_score}/5).\n"
                f"Narrative: {narrative[:300]}..."
            )
