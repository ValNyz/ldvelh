"""Arbitrate step: the dice of the turn (resumed Fate roll or new mechanical step).

The roll is only computed and announced here (roll_result): its effects are
applied by the commit step, in the turn's transaction (#16).

HALT means the turn stops here: the engine offered an invocation on the roll (a
failed Fate roll: roll_pending sent, the turn resumes later with its roll_id).
While a roll waits, any other message gets the same roll_pending again: it cannot
be dodged (#32).
"""

import logging
from dataclasses import dataclass
from uuid import UUID

import asyncpg

from domain.errors import TurnError
from domain.turn import InvocationOffer, PendingRoll
from pipeline.context import TurnContext
from pipeline.steps.load import Prepared
from repos import turns
from schema.engine import MechanicalDecision, MechanicalResult, RollResult
from services.engine.mechanical_service import MechanicalStepUnavailable, run_mechanical_step
from services.pending_roll import load_pending_roll

logger = logging.getLogger(__name__)

ONE_PENDING_PER_GAME = "mechanic_rolls_one_pending_per_game"  # unique index (#32)


@dataclass(frozen=True)
class Arbitration:
    mechanical: MechanicalResult | None
    resumed_roll_id: UUID | None


HALT = object()


async def _resume_roll(ctx: TurnContext, pending: PendingRoll | None) -> Arbitration:
    """Resume the stored roll with the invoked aspects (+2 each, from the original roll).

    `pending` is the roll load matched with the request's roll_id; None means stale.
    """
    request = ctx.request
    if pending is None:
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
    return Arbitration(mechanical=mechanical, resumed_roll_id=pending.id)


async def _offer_invocation(ctx: TurnContext, prepared: Prepared,
                            mechanical: MechanicalResult) -> bool:
    """When the engine offers an invocation on the roll, store it and pause the turn."""
    offer = ctx.engine.invocation_offer(mechanical.roll, prepared.context.engine_stats)
    if offer is None:
        return False
    pending = await _store_or_existing_pending(ctx, prepared, mechanical, offer)
    await ctx.sink.send_roll_pending(pending.offer())
    return True


async def _store_or_existing_pending(ctx: TurnContext, prepared: Prepared,
                                     mechanical: MechanicalResult,
                                     offer: InvocationOffer) -> PendingRoll:
    """Store the new pending roll; if one was stored since load (one per game), that one."""
    game_id = ctx.request.game_id
    async with ctx.pool.acquire() as conn:
        try:
            roll_id = await turns.store_pending_roll(
                conn, game_id, mechanical.roll, prepared.player_message,
                ctx.snapshot.current_cycle,
            )
        except asyncpg.UniqueViolationError as exc:
            if getattr(exc, "constraint_name", None) != ONE_PENDING_PER_GAME:
                raise
            existing = await load_pending_roll(conn, game_id, ctx.engine)
            if existing is None:  # resolved meanwhile: nothing coherent to offer
                raise
            logger.warning(f"[TURN:{ctx.ref}] A roll was already pending for game "
                           f"{game_id}: offering it again, this roll is dropped")
            return existing
    return PendingRoll(id=roll_id, roll=mechanical.roll.model_dump(),
                       player_message=prepared.player_message, aspects=offer.aspects,
                       fate_points=offer.fate_points)


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

    if await _offer_invocation(ctx, prepared, mechanical):
        return HALT

    await ctx.sink.send_roll_result(mechanical.roll.model_dump())
    return Arbitration(mechanical=mechanical, resumed_roll_id=None)


async def arbitrate(ctx: TurnContext, prepared: Prepared):
    """Arbitration of the turn, or HALT when the turn must stop before narration."""
    if ctx.request.roll_id:
        return await _resume_roll(ctx, prepared.resumed_roll)
    if prepared.pending_roll:
        # A roll still waits for the player's choice: offer it again, roll nothing.
        await ctx.sink.send_roll_pending(prepared.pending_roll.offer())
        return HALT
    # The arrival scene is narration only: no dice on the opening text.
    if ctx.engine.needs_mechanical_step() and prepared.context.engine_stats and not prepared.is_arrival:
        return await _roll_dice(ctx, prepared)
    return Arbitration(mechanical=None, resumed_roll_id=None)
