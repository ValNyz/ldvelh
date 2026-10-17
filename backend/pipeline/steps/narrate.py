"""Narrate step: prompts, streamed narration and its lenient validation."""

import logging
from dataclasses import dataclass

from llm.session import Purpose
from pipeline import narration_stream
from pipeline.context import TurnContext
from pipeline.steps.arbitrate import Arbitration
from pipeline.steps.load import Prepared
from prompts.narrator_prompt import build_narrator_context_prompt, build_narrator_system_prompt
from schema import NarrationOutput
from schema.narration import NarrationInvalid, parse_narration
from services.game_service import GameService

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Narrated:
    narration: NarrationOutput
    display_text: str
    cost: dict | None


def _log_llm_context(system_prompt: str, llm_messages: list[dict]) -> None:
    logger.info(
        f"[CHAT] Multi-turn: {len(llm_messages)} messages "
        f"({len(llm_messages) - 1} history + 1 context)"
    )
    logger.info(f"[CHAT] === SYSTEM PROMPT ===\n{system_prompt}")
    for i, msg in enumerate(llm_messages):
        content = msg["content"]
        if isinstance(content, list):
            content = content[0]["text"] if content else ""
        logger.info(f"[CHAT] === MESSAGE [{i}] ({msg['role']}) ===\n{content}")


def _validate(ctx: TurnContext, parsed: dict | None) -> NarrationOutput:
    if not parsed:
        raise NarrationInvalid("empty narrator output")
    narration, dropped = parse_narration(
        parsed, current_time=ctx.snapshot.current_time,
        current_location=ctx.snapshot.current_location_name or "",
    )
    if dropped:
        # Logged only: nothing about dropped fields reaches the player.
        logger.warning(f"[NARRATE] Dropped invalid optional fields: {dropped}")
    return narration


async def narrate(ctx: TurnContext, prepared: Prepared, arbitration: Arbitration) -> Narrated:
    engine_type = ctx.snapshot.engine
    game_service = GameService(ctx.pool)

    # Build engine + genre-aware prompts
    system_prompt = build_narrator_system_prompt(engine_type, genre=prepared.context.genre)
    context_prompt = build_narrator_context_prompt(
        prepared.context, engine_type, arbitration.mechanical
    )
    logger.debug(f"[CHAT] context prompt: {len(context_prompt)} chars")

    # Multi-turn messages (history + context prompt); assistant history wrapped
    # in JSON for providers that need it.
    json_history = getattr(ctx.session.provider_for(Purpose.NARRATION), "FORCE_JSON", False)
    llm_messages = await game_service.build_llm_messages(
        ctx.request.game_id, ctx.snapshot.current_cycle, context_prompt,
        json_history=json_history,
        cache_control=ctx.session.caps.cache_control,
    )
    _log_llm_context(system_prompt, llm_messages)

    result = await narration_stream.stream_narration(
        ctx.session, ctx.sink, system_prompt=system_prompt, messages=llm_messages,
        world_gen=False,
    )
    narration = _validate(ctx, result.parsed)
    return Narrated(narration=narration, display_text=result.display_text, cost=result.cost)
