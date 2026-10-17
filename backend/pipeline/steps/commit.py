"""Commit step: every write of the turn, in the order of the legacy handler."""

import json
import logging
from dataclasses import dataclass
from uuid import UUID

from pipeline.context import TurnContext
from pipeline.steps.arbitrate import Arbitration
from pipeline.steps.load import Prepared
from pipeline.steps.narrate import Narrated
from schema.narration import NarrationOutput
from schema.sse_payload import NarratorDeltasStored
from services.game_service import GameService

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Committed:
    state: dict  # result of process_light: cycle, time, location, npcs_present, date
    assistant_message_id: UUID
    narrator_deltas: dict


def _stored_deltas(narration: NarrationOutput, cost: dict | None) -> dict:
    return NarratorDeltasStored(
        credit_delta=narration.credit_delta.model_dump() if narration.credit_delta else None,
        inventory_hints=[h.model_dump() for h in narration.inventory_hints],
        entity_reveals=[r.model_dump() for r in narration.entity_reveals],
        extraction_triggers=narration.extraction_triggers,
        cost=cost if cost else None,
    ).model_dump(exclude_none=True)


async def _apply_narration(ctx: TurnContext, game_service: GameService,
                           narration: NarrationOutput) -> dict:
    """Game state (cycle, time, location), narrator deltas, info requests."""
    game_id = ctx.request.game_id
    process_result = await game_service.process_light(
        game_id, narration, ctx.snapshot.current_cycle
    )
    # Narrator deltas applied immediately (credits, entity reveals, compels)
    if narration.credit_delta or narration.entity_reveals or narration.compel_result:
        delta_result = await game_service.apply_narrator_deltas(
            game_id, narration, process_result["cycle"]
        )
        logger.info(f"[CHAT] Deltas applied: {json.dumps(delta_result, default=str)}")
    # Info requests for the next turn
    if narration.info_requests:
        await game_service.store_info_requests(game_id, narration.info_requests)
        logger.info(f"[CHAT] Info requests stored: {narration.info_requests}")
    return process_result


async def _log_roll(ctx: TurnContext, game_service: GameService, arbitration: Arbitration,
                    assistant_msg_id: UUID, cycle: int) -> None:
    """Log the mechanical roll with its message reference."""
    mechanical = arbitration.mechanical
    if not (mechanical and mechanical.roll):
        return
    if arbitration.resumed_roll_id:
        # Update the resumed pending roll with its message_id
        await game_service.update_mechanic_roll(
            arbitration.resumed_roll_id,
            mechanical.roll.model_dump(),
            mechanical.roll.outcome,
            message_id=assistant_msg_id,
        )
        return
    await game_service.log_mechanic_roll(
        game_id=ctx.request.game_id,
        message_id=assistant_msg_id,
        engine=ctx.snapshot.engine,
        skill_used=mechanical.roll.details.get("skill_name"),
        roll_details=mechanical.roll.model_dump(),
        outcome=mechanical.roll.outcome,
        complication=mechanical.roll.complication,
        cycle=cycle,
    )


async def commit_turn(ctx: TurnContext, prepared: Prepared, arbitration: Arbitration,
                      narrated: Narrated) -> Committed:
    game_service = GameService(ctx.pool)
    game_id = ctx.request.game_id
    process_result = await _apply_narration(ctx, game_service, narrated.narration)
    narrator_deltas = _stored_deltas(narrated.narration, narrated.cost)

    # Snapshot engine state for rollback support
    engine_snapshot = None
    if ctx.snapshot.engine != "none":
        async with ctx.pool.acquire() as snap_conn:
            engine_snapshot = await ctx.engine.snapshot_state(snap_conn, game_id)

    _, assistant_msg_id = await game_service.save_messages(
        game_id=game_id,
        # Keep the protocol token (e.g. __ARRIVEE__) so the chat history hides it,
        # as before the arrival text substitution.
        user_message=ctx.request.message,
        assistant_message=narrated.display_text,
        cycle=process_result["cycle"],
        time=process_result.get("time"),
        game_date=process_result.get("date"),
        location_ref=process_result["location"],
        narrator_deltas=narrator_deltas,
        engine_snapshot=engine_snapshot,
    )
    await _log_roll(ctx, game_service, arbitration, assistant_msg_id, process_result["cycle"])
    return Committed(state=process_result, assistant_message_id=assistant_msg_id,
                     narrator_deltas=narrator_deltas)
