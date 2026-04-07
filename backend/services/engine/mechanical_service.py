"""
LDVELH - Mechanical Service
Runs the mechanical LLM step before narration for dice-based engines.
Uses Haiku for cost efficiency.
"""

import logging

from prompts.mechanical_prompt import (
    build_mechanical_context,
    get_mechanical_system_prompt,
)
from schema.engine import MechanicalDecision, MechanicalResult
from services.engine.base import BaseEngine
from services.llm_service import LLMService
from utils import parse_json_response

logger = logging.getLogger(__name__)

# Haiku model for mechanical decisions (cheap + fast)
MECHANICAL_MODEL = "claude-haiku-4-5"


async def run_mechanical_step(
    engine: BaseEngine,
    engine_stats: dict,
    player_message: str,
    context_summary: str,
    world_difficulty: str,
    llm_service: LLMService,
    provider_name: str = "anthropic",
    api_key: str | None = None,
) -> MechanicalResult | None:
    """Run the mechanical LLM step. Returns None if no test needed.

    Pipeline:
    1. Build prompt with character stats + player action
    2. Call LLM (Haiku) to get MechanicalDecision
    3. If requires_test: engine.roll_dice(decision)
    4. Return MechanicalResult with decision + optional roll
    """
    if not engine.needs_mechanical_step():
        return None

    engine_type = engine.engine_type.value
    system_prompt = get_mechanical_system_prompt(engine_type)
    user_message = build_mechanical_context(
        player_message=player_message,
        engine_stats=engine_stats,
        world_difficulty=world_difficulty,
        context_summary=context_summary,
    )

    logger.info(f"[MECHANICAL] Running mechanical step for engine={engine_type}")

    # Call Haiku for the decision
    parsed = await llm_service.extract_text(
        system_prompt=system_prompt,
        user_message=user_message,
        provider_name=provider_name,
        api_key=api_key,
        model=MECHANICAL_MODEL,
    )

    if not parsed:
        logger.warning("[MECHANICAL] LLM returned no parseable response, skipping test")
        return None

    # Parse the decision
    try:
        decision = MechanicalDecision(**parsed)
    except Exception as e:
        logger.warning(f"[MECHANICAL] Failed to parse decision: {e}")
        return None

    # Get cost from last call
    cost = getattr(llm_service, "_last_call_cost", None)

    if not decision.requires_test:
        logger.info(f"[MECHANICAL] No test needed: {decision.reason}")
        return MechanicalResult(decision=decision, roll=None, cost=cost)

    # Roll dice
    logger.info(
        f"[MECHANICAL] Test required: {decision.skill} "
        f"(value={decision.skill_value}) vs difficulty={decision.difficulty} "
        f"— {decision.reason}"
    )
    roll = engine.roll_dice(decision)

    logger.info(
        f"[MECHANICAL] Roll result: dice={roll.dice}, total={roll.skill_total}, "
        f"outcome={roll.outcome}, shifts={roll.shifts}"
    )

    return MechanicalResult(decision=decision, roll=roll, cost=cost)
