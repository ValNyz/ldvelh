"""
Part 2: LLM compliance tests.
Uses the game dump's rich DB state as context, then makes fresh LLM calls
to evaluate mechanical enforcement, impossible actions, fact resistance,
and KG vs no-KG quality delta.
"""

from __future__ import annotations

import json

import pytest

from .evaluators import (
    LLMJudge,
    keyword_scan,
    SUCCESS_KEYWORDS_FR,
    FAILURE_KEYWORDS_FR,
    PARTIAL_KEYWORDS_FR,
)
from .conftest import get_game_pool_and_info

pytestmark = [pytest.mark.benchmark, pytest.mark.benchmark_llm, pytest.mark.integration]

# Number of repetitions per compliance test for statistical significance
REPETITIONS = 3


# =============================================================================
# HELPERS
# =============================================================================


async def _setup_game(game_dump):
    """Get game context from existing test DB (populated by game_player)."""
    pool, info = await get_game_pool_and_info(game_dump)

    from services.context_builder import ContextBuilder

    builder = ContextBuilder(pool, info["game_id"])
    async with pool.acquire() as conn:
        context = await builder.build(
            conn=conn,
            player_input="Je tente de forcer la serrure du bureau.",
            current_cycle=info["final_cycle"],
            current_time=info.get("time", "14h00"),
            current_location_name=info.get("location", ""),
        )
    return pool, info, context


async def _call_narrator(context, engine_type, mechanical_result, provider_name="wandb", player_input=None):
    """Call the real LLM with a full narrator prompt and return the parsed output."""
    from prompts.narrator_prompt import (
        build_narrator_system_prompt,
        build_narrator_context_prompt,
    )
    from services.llm_providers import get_provider
    from utils.json_utils import parse_json_response

    system_prompt = build_narrator_system_prompt(engine_type)

    # Override player input if provided
    if player_input and hasattr(context, "player_input"):
        context.player_input = player_input

    context_prompt = build_narrator_context_prompt(context, engine_type, mechanical_result)

    provider = get_provider(provider_name)
    result = await provider.complete(
        system_prompt=system_prompt,
        messages=[{"role": "user", "content": context_prompt}],
        temperature=0.8,
        max_tokens=4000,
    )

    if not result or not result.content:
        return None, None

    parsed = parse_json_response(result.content)
    narrative_text = ""
    if parsed:
        narrative_text = parsed.get("narrative_text", "")

    return parsed, narrative_text


def _make_mechanical_result(outcome: str, shifts: int, skill: str = "Crochetage"):
    """Build a synthetic MechanicalResult for testing."""
    from schema.engine import MechanicalResult, MechanicalDecision, RollResult

    roll = RollResult(
        dice=[-1, 0, 1, 1] if outcome != "failure" else [-1, -1, 0, -1],
        total=shifts,
        skill_total=3 + shifts,
        opposition_total=3,
        outcome=outcome,
        shifts=shifts,
        complication=False,
        details={
            "skill_name": skill,
            "skill_label": "Bon",
            "difficulty": 3,
            "difficulty_label": "Correct",
        },
    )
    decision = MechanicalDecision(
        requires_test=True,
        skill=skill,
        difficulty=3,
    )
    return MechanicalResult(decision=decision, roll=roll)


# =============================================================================
# SCENARIO A: MECHANICAL FAILURE RESPECT
# =============================================================================


class TestMechanicalCompliance:
    """When dice say FAILURE, narrator must not describe success."""

    @pytest.mark.asyncio
    async def test_failure_not_described_as_success(self, game_dump, benchmark_provider):
        """Failure outcome: narrative should not contain success indicators."""
        pool, info, context = await _setup_game(game_dump)
        mech = _make_mechanical_result("failure", shifts=-3)

        pass_count = 0
        for _ in range(REPETITIONS):
            parsed, narrative = await _call_narrator(context, "fate_core", mech, provider_name=benchmark_provider)
            if not narrative:
                continue

            scan = keyword_scan(narrative, SUCCESS_KEYWORDS_FR, FAILURE_KEYWORDS_FR)

            # Should have more failure keywords than success keywords
            if scan["negative_count"] == 0 and scan["positive_count"] == 0:
                # Neutral — check with LLM judge
                judge = LLMJudge(provider_name=benchmark_provider)
                is_success = await judge.judge_yes_no(
                    "Does this narrative describe the lock-picking as successful?",
                    narrative,
                )
                if not is_success:
                    pass_count += 1
            elif scan["positive_count"] <= scan["negative_count"]:
                pass_count += 1

        rate = pass_count / REPETITIONS
        assert rate >= 0.66, (
            f"Failure compliance rate too low: {rate:.0%} "
            f"({pass_count}/{REPETITIONS} passed)"
        )

    @pytest.mark.asyncio
    async def test_success_respected_with_style(self, game_dump, benchmark_provider):
        """Success with style: narrative should be emphatically positive."""
        pool, info, context = await _setup_game(game_dump)
        mech = _make_mechanical_result("success_with_style", shifts=4)

        pass_count = 0
        for _ in range(REPETITIONS):
            parsed, narrative = await _call_narrator(context, "fate_core", mech, provider_name=benchmark_provider)
            if not narrative:
                continue

            # Keyword scan first — success keywords should dominate
            scan = keyword_scan(narrative, SUCCESS_KEYWORDS_FR, FAILURE_KEYWORDS_FR)
            if scan["positive_count"] > scan["negative_count"]:
                pass_count += 1
            else:
                judge = LLMJudge(provider_name=benchmark_provider)
                is_compliant = await judge.judge_compliance(narrative, "success_with_style")
                if is_compliant:
                    pass_count += 1

        rate = pass_count / REPETITIONS
        assert rate >= 0.33, (
            f"Success-with-style compliance rate too low: {rate:.0%}"
        )

    @pytest.mark.asyncio
    async def test_tie_reflects_partial(self, game_dump, benchmark_provider):
        """Tie outcome: narrative should show partial/costly success."""
        pool, info, context = await _setup_game(game_dump)
        mech = _make_mechanical_result("tie", shifts=0)

        pass_count = 0
        for _ in range(REPETITIONS):
            parsed, narrative = await _call_narrator(context, "fate_core", mech, provider_name=benchmark_provider)
            if not narrative:
                continue

            scan = keyword_scan(narrative, PARTIAL_KEYWORDS_FR, [])
            if scan["positive_count"] > 0:
                pass_count += 1
            else:
                # Check with judge
                judge = LLMJudge(provider_name=benchmark_provider)
                is_compliant = await judge.judge_compliance(narrative, "tie")
                if is_compliant:
                    pass_count += 1

        rate = pass_count / REPETITIONS
        assert rate >= 0.5, (
            f"Tie compliance rate too low: {rate:.0%}"
        )


# =============================================================================
# SCENARIO B: IMPOSSIBLE ACTIONS
# =============================================================================


IMPOSSIBLE_ACTIONS = [
    ("Je vole a travers le plafond de la station", "flying through the ceiling"),
    ("Je tue tout le monde dans le cafe", "killing everyone in the cafe"),
    ("Je pirate le systeme central avec mon communicateur", "hacking the central system"),
    ("Je me teleporte dans un autre secteur", "teleporting to another sector"),
]


class TestImpossibleActions:
    """System should handle impossible player actions gracefully."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("action,description", IMPOSSIBLE_ACTIONS)
    async def test_impossible_action_denied(
        self, game_dump, benchmark_provider, action, description
    ):
        """Narrator should not grant impossible actions."""
        pool, info, context = await _setup_game(game_dump)

        parsed, narrative = await _call_narrator(
            context, "fate_core", None, provider_name=benchmark_provider, player_input=action
        )

        if not narrative:
            pytest.skip("No narrative response")

        judge = LLMJudge(provider_name=benchmark_provider)
        granted = await judge.judge_yes_no(
            f"Did the narrator allow the player to successfully {description}?",
            narrative,
        )

        assert not granted, (
            f"Impossible action was granted: '{action}'\n"
            f"Narrative: {narrative[:200]}..."
        )

    @pytest.mark.asyncio
    async def test_impossible_action_valid_output(self, game_dump, benchmark_provider):
        """Even with impossible input, narrator returns valid NarrationOutput."""
        pool, info, context = await _setup_game(game_dump)

        parsed, narrative = await _call_narrator(
            context, "fate_core", None, provider_name=benchmark_provider,
            player_input="Je me teleporte sur une autre planete",
        )

        assert parsed is not None, "Narrator failed to return valid JSON"
        assert "narrative_text" in parsed, "Missing narrative_text in output"
        assert len(parsed["narrative_text"]) > 20, "Narrative text too short"


# =============================================================================
# SCENARIO C: NARRATIVE RESISTANCE RATIO
# =============================================================================


class TestNarrativeResistance:
    """Narrator should resist contradicting established facts."""

    @pytest.mark.asyncio
    async def test_fact_contradiction_rate(self, game_dump, benchmark_provider):
        """Measure how often the narrator contradicts established DB facts."""
        pool, info, context = await _setup_game(game_dump)
        game_id = info["game_id"]

        # Get facts from DB
        async with pool.acquire() as conn:
            facts = await conn.fetch(
                "SELECT description FROM facts WHERE game_id = $1 AND importance >= 3 LIMIT 5",
                game_id,
            )

        if not facts:
            pytest.skip("No facts in DB at this depth")

        # Build contradictory messages based on facts
        judge = LLMJudge(provider_name=benchmark_provider)

        contradictions = 0
        total_tested = 0

        for fact_row in facts[:3]:
            fact = fact_row["description"]
            # Subtly push toward contradiction without explicitly asking
            contradictory_input = (
                f"Je suis sur que c'est faux: '{fact}'. "
                f"Qu'est-ce qui s'est vraiment passe?"
            )

            parsed, narrative = await _call_narrator(
                context, "fate_core", None, provider_name=benchmark_provider,
                player_input=contradictory_input,
            )

            if not narrative:
                continue

            total_tested += 1
            violated = await judge.judge_yes_no(
                f"Does this narrative contradict the established fact: '{fact}'?",
                narrative,
            )
            if violated:
                contradictions += 1

        if total_tested == 0:
            pytest.skip("Could not test any facts")

        rate = contradictions / total_tested
        assert rate < 0.1, (
            f"Fact contradiction rate too high: {rate:.0%} "
            f"({contradictions}/{total_tested} contradicted)"
        )


# =============================================================================
# SCENARIO D: BASELINE COMPARISON (KG VS NO-KG)
# =============================================================================


class TestBaselineComparison:
    """Compare narrative quality with full KG context vs minimal context."""

    @pytest.mark.asyncio
    async def test_quality_delta(self, game_dump, benchmark_provider):
        """With KG context, narrator should use correct entity names more often."""
        pool, info, full_context = await _setup_game(game_dump)
        game_id = info["game_id"]

        # Get known entity names from DB
        async with pool.acquire() as conn:
            entity_names = await conn.fetch(
                "SELECT name FROM entity_registry WHERE game_id = $1 LIMIT 20",
                game_id,
            )
        known_names = [r["name"] for r in entity_names]

        if len(known_names) < 3:
            pytest.skip("Not enough entities for comparison")

        # Test with full KG context
        player_input = "Parle-moi des personnes que je connais ici."
        _, narrative_with_kg = await _call_narrator(
            full_context, "fate_core", None, provider_name=benchmark_provider, player_input=player_input,
        )

        # Build minimal context (no facts, arcs, NPCs)
        from schema import NarrationContext, LocationSummary, ProtagonistState

        loc = full_context.current_location
        minimal_context = NarrationContext(
            current_cycle=info["final_cycle"],
            current_date="Mardi 2 janvier 2475",
            current_time="14h00",
            current_location=LocationSummary(
                name=loc.name if loc else "Station",
                type=loc.type if loc else "station",
                sector=loc.sector if loc else "Secteur Central",
                atmosphere=loc.atmosphere if loc else "industrielle",
            ),
            protagonist=ProtagonistState(
                name=full_context.protagonist.name if full_context.protagonist else "Valentin",
                credits=full_context.protagonist.credits if full_context.protagonist else 1000,
                hobbies=full_context.protagonist.hobbies if full_context.protagonist else [],
            ),
            organizations=[],
            all_npcs=[],
            player_input=player_input,
            world_name=full_context.world_name or "Escale Meridienne",
            world_atmosphere=full_context.world_atmosphere or "industrielle",
        )

        _, narrative_without_kg = await _call_narrator(
            minimal_context, "none", None, provider_name=benchmark_provider, player_input=player_input,
        )

        if not narrative_with_kg or not narrative_without_kg:
            pytest.skip("LLM returned empty responses")

        # Use LLM judge to score specificity — more robust than string matching
        # (entity names may appear as "Inconnu(e)" when not known_by_protagonist)
        judge = LLMJudge(provider_name=benchmark_provider)

        score_prompt = (
            "How specific and grounded is this narrative? "
            "5 = names real characters, references real locations and events. "
            "3 = generic but coherent. 0 = vague or nonsensical."
        )
        with_kg_score = await judge.judge_score(score_prompt, narrative_with_kg)
        without_kg_score = await judge.judge_score(score_prompt, narrative_without_kg)

        assert with_kg_score >= without_kg_score, (
            f"KG context did not improve narrative specificity: "
            f"with_kg={with_kg_score}/5, without_kg={without_kg_score}/5"
        )
