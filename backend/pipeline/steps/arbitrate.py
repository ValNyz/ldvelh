"""Arbitrate step: the dice of the turn (resumed Fate roll or new mechanical step).

The roll is only computed and announced here (roll_result): its effects are
applied by the commit step, in the turn's transaction (#16).

HALT means the turn stops here: the player may invoke aspects on a failed Fate
roll (roll_pending sent, the turn resumes later with its roll_id). While a roll
waits, any other message gets the same roll_pending again: it cannot be dodged (#32).
"""

from dataclasses import dataclass
from uuid import UUID

from domain.errors import TurnError
from domain.turn import PendingRoll
from pipeline.context import TurnContext
from pipeline.steps.load import Prepared
from repos import turns
from schema.engine import MechanicalDecision, MechanicalResult, RollResult
from services.engine.fate_core import aspect_names
from services.engine.mechanical_service import MechanicalStepUnavailable, run_mechanical_step


@dataclass(frozen=True)
class Arbitration:
    mechanical: MechanicalResult | None
    resumed_roll_id: UUID | None
    # Resumed roll: the stored action, narrated and saved instead of the received message.
    player_message: str | None = None


HALT = object()


async def _resume_roll(ctx: TurnContext, pending: PendingRoll | None) -> Arbitration:
    """Resume the stored roll with the invoked aspects (+2 each, from the original roll)."""
    request = ctx.request
    if pending is None or pending.id != request.roll_id:
        raise TurnError("roll_not_pending", "Ce jet n'est plus en attente.")
    roll = ctx.engine.apply_invocation(RollResult(**pending.roll), request.invoked_aspects,
                                       pending.aspects, pending.fate_points)
    details = roll.details
    mechanical = MechanicalResult(
        decision=MechanicalDecision(
            requires_test=True,
            skill=details.get("skill_name"),
            skill_value=details.get("skill_value"),
            difficulty=details.get("difficulty"),
        ),
        roll=roll,
    )
    # Stress + fate point deduction and the roll claim happen at commit.
    await ctx.sink.send_roll_result(roll.model_dump())
    return Arbitration(mechanical=mechanical, resumed_roll_id=pending.id,
                       player_message=pending.player_message)


async def _offer_invocation(ctx: TurnContext, prepared: Prepared,
                            mechanical: MechanicalResult) -> bool:
    """On a failed Fate roll with fate points and aspects, store it and pause the turn."""
    stats = prepared.context.engine_stats
    fate_points = stats.get("fate_points", 0)
    aspects = aspect_names(stats)
    if not (fate_points > 0 and aspects):
        return False
    async with ctx.pool.acquire() as conn:
        roll_id = await turns.store_pending_roll(
            conn, ctx.request.game_id, mechanical.roll, ctx.request.message,
            ctx.snapshot.current_cycle,
        )
    pending = PendingRoll(id=roll_id, roll=mechanical.roll.model_dump(),
                          player_message=ctx.request.message, aspects=aspects,
                          fate_points=fate_points)
    await ctx.sink.send_roll_pending(pending.offer())
    return True


async def _roll_dice(ctx: TurnContext, prepared: Prepared):
    """Run the mechanical step, then send the roll (or pause for invocation)."""
    try:
        mechanical = await run_mechanical_step(
            engine=ctx.engine,
            engine_stats=prepared.context.engine_stats,
            player_message=prepared.player_input,
            context_summary="",  # TODO: build short context summary
            world_difficulty="moderate",  # TODO: from world_config
            session=ctx.session,
        )
    except MechanicalStepUnavailable:
        # #10: tell the player instead of silently narrating without dice
        mechanical = None
        await ctx.sink.send_warning(
            "Jet de dés indisponible pour ce tour : le modèle n'a pas "
            "renvoyé de décision exploitable."
        )

    if not (mechanical and mechanical.roll):
        return Arbitration(mechanical=mechanical, resumed_roll_id=None)

    if (ctx.snapshot.engine == "fate_core" and mechanical.roll.outcome == "failure"
            and await _offer_invocation(ctx, prepared, mechanical)):
        return HALT

    await ctx.sink.send_roll_result(mechanical.roll.model_dump())
    return Arbitration(mechanical=mechanical, resumed_roll_id=None)


async def arbitrate(ctx: TurnContext, prepared: Prepared):
    """Arbitration of the turn, or HALT when the turn must stop before narration."""
    if ctx.request.roll_id:
        return await _resume_roll(ctx, prepared.pending_roll)
    if prepared.pending_roll:
        # A roll still waits for the player's choice: offer it again, roll nothing.
        await ctx.sink.send_roll_pending(prepared.pending_roll.offer())
        return HALT
    # The arrival scene is narration only: no dice on the opening text.
    if ctx.engine.needs_mechanical_step() and prepared.context.engine_stats and not prepared.is_arrival:
        return await _roll_dice(ctx, prepared)
    return Arbitration(mechanical=None, resumed_roll_id=None)
