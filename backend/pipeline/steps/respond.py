"""Respond step: the done payload, sent once the turn is saved, then saved."""

from pipeline.context import TurnContext
from pipeline.steps.arbitrate import Arbitration
from pipeline.steps.commit import Committed
from pipeline.steps.narrate import Narrated
from schema.engine import MechanicalResult
from schema.sse_payload import SSEDonePayload, SSEGameState, SSEMeta, SSEUIHints
from services.game_service import GameService


def _merged_game(game: dict, process_result: dict) -> dict:
    """Client game state overridden by what this turn just committed."""
    merged = {
        **game,
        "current_cycle": process_result["cycle"],
        "time": process_result["time"],
        "current_location": process_result["location"],
        "npcs_present": process_result["npcs_present"],
    }
    if process_result.get("date"):
        merged["game_date"] = process_result["date"]
    return merged


def build_done_payload(client_state: dict, committed: Committed, engine_type: str,
                       narrated: Narrated, mechanical: MechanicalResult | None) -> SSEDonePayload:
    """Done payload of a narration turn (pure)."""
    narration_cost = narrated.cost
    mech_cost = mechanical.cost if mechanical else None
    hints = narrated.narration.inventory_hints
    return SSEDonePayload(
        game_state=SSEGameState(
            game=_merged_game(client_state["game"], committed.state),
            player=client_state["player"],
            ai=client_state.get("ai"),
            world_created=client_state.get("world_created", True),
            engine=engine_type if engine_type != "none" else None,
            engine_stats=client_state["player"].get("engine_stats"),
        ),
        meta=SSEMeta(narration_cost=narration_cost, mechanical_cost=mech_cost)
        if narration_cost or mech_cost
        else None,
        ui=SSEUIHints(inventory_hints=[h.model_dump() for h in hints]) if hints else None,
    )


async def respond(ctx: TurnContext, narrated: Narrated, arbitration: Arbitration,
                  committed: Committed) -> None:
    state = await GameService(ctx.pool).load_game_state(ctx.request.game_id)
    payload = build_done_payload(state, committed, ctx.snapshot.engine, narrated,
                                 arbitration.mechanical)
    await ctx.sink.send_done(narrated.display_text, payload.model_dump(exclude_none=True))
    await ctx.sink.send_saved()
