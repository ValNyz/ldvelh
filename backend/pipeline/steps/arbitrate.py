"""Arbitrate step: the dice of the turn (resumed Fate roll or new mechanical step).

HALT means the turn stops here: the pending roll is missing, or the player may
invoke aspects on a failed Fate roll (roll_pending sent, the turn resumes later).
"""

from dataclasses import dataclass
from uuid import UUID

from pipeline.context import TurnContext
from pipeline.steps.load import Prepared
from schema.engine import MechanicalDecision, MechanicalResult, RollResult
from services.engine.mechanical_service import MechanicalStepUnavailable, run_mechanical_step
from services.game_service import GameService


@dataclass(frozen=True)
class Arbitration:
    mechanical: MechanicalResult | None
    resumed_roll_id: UUID | None


HALT = object()


def _resume_invocation(roll_data: dict, invoked: list[str]) -> None:
    """Apply +2 per invoked aspect to a stored Fate roll and recompute its outcome."""
    bonus = len(invoked) * 2
    roll_data["skill_total"] = roll_data["skill_total"] + bonus
    difficulty = roll_data.get("details", {}).get("difficulty", 0)
    new_shifts = roll_data["skill_total"] - difficulty
    if new_shifts < 0:
        roll_data["outcome"] = "failure"
    elif new_shifts == 0:
        roll_data["outcome"] = "tie"
    elif new_shifts >= 3:
        roll_data["outcome"] = "success_with_style"
    else:
        roll_data["outcome"] = "success"
    roll_data["shifts"] = new_shifts
    roll_data.setdefault("details", {})
    roll_data["details"]["invoked_aspects"] = invoked
    roll_data["details"]["invocation_bonus"] = bonus
    roll_data["details"]["fate_points_spent"] = len(invoked)


async def _resume_roll(ctx: TurnContext):
    """Resume from a Fate Core aspect invocation, using the stored roll."""
    game_service = GameService(ctx.pool)
    request = ctx.request
    pending = await game_service.load_pending_roll(request.game_id, request.roll_id)
    if not pending:
        await ctx.sink.send_error("Pending roll not found", recoverable=True)
        return HALT

    roll_data = dict(pending["roll_details"])
    invoked = list(request.invoked_aspects)
    if invoked:
        _resume_invocation(roll_data, invoked)

    updated_roll = RollResult(**roll_data)
    details = roll_data.get("details", {})
    mechanical = MechanicalResult(
        decision=MechanicalDecision(
            requires_test=True,
            skill=details.get("skill_name"),
            skill_value=details.get("skill_value"),
            difficulty=details.get("difficulty"),
        ),
        roll=updated_roll,
    )

    # Apply roll result (stress + fate point deduction)
    async with ctx.pool.acquire() as apply_conn:
        await ctx.engine.apply_roll_result(
            apply_conn, request.game_id, updated_roll, ctx.snapshot.current_cycle,
        )
    await game_service.update_mechanic_roll(request.roll_id, roll_data, updated_roll.outcome)
    await ctx.sink.send_roll_result(updated_roll.model_dump())
    return Arbitration(mechanical=mechanical, resumed_roll_id=request.roll_id)


async def _offer_invocation(ctx: TurnContext, prepared: Prepared,
                            mechanical: MechanicalResult) -> bool:
    """On a failed Fate roll with fate points and aspects, store it and pause the turn."""
    stats = prepared.context.engine_stats
    fate_points = stats.get("fate_points", 0)
    aspects = stats.get("aspects", [])
    if not (fate_points > 0 and aspects):
        return False
    roll = mechanical.roll
    roll_id = await GameService(ctx.pool).log_mechanic_roll(
        game_id=ctx.request.game_id,
        message_id=None,
        engine=ctx.snapshot.engine,
        skill_used=roll.details.get("skill_name"),
        roll_details=roll.model_dump(),
        outcome=roll.outcome,
        complication=roll.complication,
        cycle=ctx.snapshot.current_cycle,
    )
    await ctx.sink.send_roll_pending({
        "roll_id": str(roll_id),
        "roll": roll.model_dump(),
        "aspects": aspects,
        "fate_points": fate_points,
    })
    return True


async def _roll_dice(ctx: TurnContext, prepared: Prepared):
    """Run the mechanical step, then apply and send the roll (or pause for invocation)."""
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

    async with ctx.pool.acquire() as apply_conn:
        await ctx.engine.apply_roll_result(
            apply_conn, ctx.request.game_id, mechanical.roll, ctx.snapshot.current_cycle,
        )
    await ctx.sink.send_roll_result(mechanical.roll.model_dump())
    return Arbitration(mechanical=mechanical, resumed_roll_id=None)


async def arbitrate(ctx: TurnContext, prepared: Prepared):
    """Arbitration of the turn, or HALT when the turn must stop before narration."""
    if ctx.request.roll_id:
        return await _resume_roll(ctx)
    # The arrival scene is narration only: no dice on the opening text.
    if ctx.engine.needs_mechanical_step() and prepared.context.engine_stats and not prepared.is_arrival:
        return await _roll_dice(ctx, prepared)
    return Arbitration(mechanical=None, resumed_roll_id=None)
