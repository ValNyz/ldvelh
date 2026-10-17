"""
LDVELH - Mechanical Service
Runs the mechanical LLM step before narration for dice-based engines.
The model comes from the provider (cheap model where it has one, e.g. Haiku).
"""

import logging

from config import get_settings
from llm.session import LLMSession, Purpose
from prompts.mechanical_prompt import (
    build_mechanical_context,
    get_mechanical_system_prompt,
)
from schema.engine import MechanicalDecision, MechanicalResult
from services.engine.base import BaseEngine
from utils.log_safe import safe_repr

logger = logging.getLogger(__name__)


class MechanicalStepUnavailable(Exception):
    """The mechanical LLM call failed: the turn continues without dice (#10)."""


async def run_mechanical_step(
    engine: BaseEngine,
    engine_stats: dict,
    player_message: str,
    context_summary: str,
    world_difficulty: str,
    session: LLMSession,
) -> MechanicalResult | None:
    """Run the mechanical LLM step. Returns None if the engine has no mechanical step.

    Raises MechanicalStepUnavailable when the LLM gives no usable decision, so the
    caller can warn the player instead of silently skipping the dice.

    Pipeline:
    1. Build prompt with character stats + player action
    2. Call the provider's mechanical model to get MechanicalDecision
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

    settings = get_settings()
    call = await session.complete_json(
        Purpose.MECHANICAL, system_prompt, user_message,
        temperature=settings.temperature_mechanical,
        max_tokens=settings.max_tokens_mechanical,
    )
    parsed = call.value
    if not parsed:
        logger.error(f"[MECHANICAL] No usable decision from "
                     f"{session.provider_name}/{session.model_for(Purpose.MECHANICAL)}")
        raise MechanicalStepUnavailable(
            f"{session.provider_name}/{session.model_for(Purpose.MECHANICAL)}")

    # Parse the decision
    try:
        decision = MechanicalDecision(**parsed)
    except Exception as e:
        logger.error(f"[MECHANICAL] Failed to parse decision: {safe_repr(e)}")
        raise MechanicalStepUnavailable(safe_repr(e)) from e

    # Get cost from last call
    cost = call.cost

    if not decision.requires_test:
        logger.info("[MECHANICAL] No test needed")
        logger.debug(f"[MECHANICAL] Reason: {decision.reason}")
        return MechanicalResult(decision=decision, roll=None, cost=cost)

    # The arbiter picks the skill; the value comes from the character sheet (#13)
    sheet_decision = engine.resolve_roll_inputs(decision, engine_stats)
    if sheet_decision.skill_value != decision.skill_value:
        logger.info(
            f"[MECHANICAL] {decision.skill}: LLM value {decision.skill_value!r} "
            f"replaced by sheet value {sheet_decision.skill_value!r}"
        )
    decision = sheet_decision

    # Roll dice
    logger.info(
        f"[MECHANICAL] Test required: {decision.skill} "
        f"(value={decision.skill_value}) vs difficulty={decision.difficulty}"
    )
    logger.debug(f"[MECHANICAL] Reason: {decision.reason}")
    roll = engine.roll_dice(decision)

    logger.info(
        f"[MECHANICAL] Roll result: dice={roll.dice}, total={roll.skill_total}, "
        f"outcome={roll.outcome}, shifts={roll.shifts}"
    )

    return MechanicalResult(decision=decision, roll=roll, cost=cost)
