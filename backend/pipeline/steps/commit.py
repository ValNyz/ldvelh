"""Commit step: every write of the turn in ONE transaction, dice effects included.

Order: roll effects, narration state and deltas, engine snapshot and messages,
roll log, engine lock. A failure anywhere rolls the whole turn back (#16, #20).
"""

import json
import logging
from dataclasses import asdict, dataclass
from uuid import UUID

from domain.turn import AppliedDeltas, NarrationState
from pipeline.context import TurnContext
from pipeline.steps.arbitrate import Arbitration
from pipeline.steps.load import Prepared
from pipeline.steps.narrate import Narrated
from repos import turns
from schema.narration import NarrationOutput
from schema.sse_payload import NarratorDeltasStored

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Committed:
    state: NarrationState
    assistant_message_id: UUID
    narrator_deltas: dict


def _stored_credit(applied: AppliedDeltas | None) -> dict | None:
    """What the ledger did with the narrator's credit delta, never what it asked for."""
    credit = applied.credit if applied else None
    if not credit:
        return None
    return {"amount": credit["amount"], "description": credit["description"],
            "applied": credit["applied"], "error": credit["error"]}


def _stored_deltas(narration: NarrationOutput, applied: AppliedDeltas | None,
                   cost: dict | None) -> dict:
    return NarratorDeltasStored(
        credit_delta=_stored_credit(applied),
        inventory_hints=[h.model_dump() for h in narration.inventory_hints],
        entity_reveals=[r.model_dump() for r in narration.entity_reveals],
        extraction_triggers=narration.extraction_triggers,
        cost=cost if cost else None,
    ).model_dump(exclude_none=True)


async def _apply_narration(conn, game_id: UUID, narration: NarrationOutput,
                           current_cycle: int) -> tuple[NarrationState, AppliedDeltas | None]:
    """Game state (cycle, time, location), narrator deltas, info requests."""
    state = await turns.apply_narration_state(conn, game_id, narration, current_cycle)
    applied = None
    if narration.credit_delta or narration.entity_reveals or narration.compel_result:
        applied = await turns.apply_narrator_deltas(conn, game_id, narration, state.cycle)
        logger.info(f"[CHAT] Deltas applied: {json.dumps(asdict(applied), default=str)}")
    if narration.info_requests:
        await turns.store_info_requests(conn, game_id, narration.info_requests)
        logger.info(f"[CHAT] Info requests stored: {narration.info_requests}")
    return state, applied


async def _log_roll(conn, ctx: TurnContext, arbitration: Arbitration,
                    assistant_msg_id: UUID, cycle: int) -> None:
    """Log the roll with its message, or link the resumed pending roll to it."""
    roll = arbitration.mechanical.roll
    if arbitration.resumed_roll_id:
        await turns.update_mechanic_roll(conn, arbitration.resumed_roll_id, roll.model_dump(),
                                         roll.outcome, assistant_msg_id)
        return
    await turns.log_mechanic_roll(conn, ctx.request.game_id, message_id=assistant_msg_id,
                                  engine=ctx.snapshot.engine, roll=roll, cycle=cycle)


async def commit_turn(ctx: TurnContext, prepared: Prepared, arbitration: Arbitration,
                      narrated: Narrated) -> Committed:
    game_id = ctx.request.game_id
    mechanical = arbitration.mechanical
    roll = mechanical.roll if mechanical else None

    async with ctx.pool.acquire() as conn, conn.transaction():
        if roll:
            await ctx.engine.apply_roll_result(conn, game_id, roll, ctx.snapshot.current_cycle)
        state, applied = await _apply_narration(conn, game_id, narrated.narration,
                                                ctx.snapshot.current_cycle)
        narrator_deltas = _stored_deltas(narrated.narration, applied, narrated.cost)
        # Engine state after this turn's roll, for rollback support
        engine_snapshot = None
        if ctx.snapshot.engine != "none":
            engine_snapshot = await ctx.engine.snapshot_state(conn, game_id)
        _, assistant_msg_id = await turns.save_turn_messages(
            conn, game_id,
            # Keep the protocol token (e.g. __ARRIVEE__) so the chat history hides it.
            user_message=ctx.request.message,
            assistant_message=narrated.display_text,
            state=state, narrator_deltas=narrator_deltas, engine_snapshot=engine_snapshot,
        )
        if roll:
            await _log_roll(conn, ctx, arbitration, assistant_msg_id, state.cycle)
        if ctx.snapshot.engine != "none" and not ctx.snapshot.engine_locked:
            await turns.lock_engine(conn, game_id)

    return Committed(state=state, assistant_message_id=assistant_msg_id,
                     narrator_deltas=narrator_deltas)
