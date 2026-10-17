"""Load step: the roll still waiting for an aspect invocation, if any, the player's input
(stored action on a resume, arrival text substituted) and the narration context."""

import logging
from dataclasses import dataclass

from domain.game import GameSnapshot
from domain.turn import PendingRoll
from pipeline.context import TurnContext
from repos import games as games_repo
from schema.narration import NarrationContext
from services.context_builder import ContextBuilder
from services.pending_roll import load_pending_roll

logger = logging.getLogger(__name__)

ARRIVAL_TOKEN = "__ARRIVEE__"
DEFAULT_ARRIVAL_MESSAGE = "Je viens d'arriver."


@dataclass(frozen=True)
class Prepared:
    player_input: str  # what the narrator reads
    player_message: str  # what the turn saves as the user message
    is_arrival: bool
    context: NarrationContext
    pending_roll: PendingRoll | None = None


async def _build_arrival_message(conn, snapshot: GameSnapshot) -> str:
    """Player message for the arrival turn, from the game's genre arrival_prompt."""
    genre = await games_repo.get_genre(conn, snapshot.genre_id)
    if not genre or not genre.get("arrival_prompt"):
        return DEFAULT_ARRIVAL_MESSAGE
    return (
        genre["arrival_prompt"]
        .replace("{world_name}", snapshot.world_name or "")
        .replace("{protagonist_name}", snapshot.protagonist_name or "")
    )


def _resumed(ctx: TurnContext, pending_roll: PendingRoll | None) -> PendingRoll | None:
    """The pending roll this request resumes, if any (a stale roll_id fails in arbitrate)."""
    if ctx.request.roll_id and pending_roll and pending_roll.id == ctx.request.roll_id:
        return pending_roll
    return None


async def load_turn(ctx: TurnContext) -> Prepared:
    snapshot = ctx.snapshot
    # The old DTO dropped None values, so a missing location read as "".
    current_location = snapshot.current_location_name or ""
    mode_label = "LIGHT" if current_location else "FIRST_LIGHT"
    logger.info(f"[CHAT] Mode: {mode_label}, Cycle: {snapshot.current_cycle}")

    async with ctx.pool.acquire() as conn:
        pending_roll = await load_pending_roll(conn, snapshot.id, ctx.engine)
        # Resumed roll: the stored action is narrated and saved, whatever the request
        # carried (#32). Protocol token (__ARRIVEE__): narrate the genre's arrival text,
        # save the token so the chat history hides it. genre_id / world_name /
        # protagonist_name come from the snapshot (#9).
        resumed = _resumed(ctx, pending_roll)
        player_message = resumed.player_message if resumed else ctx.request.message
        is_arrival = not resumed and player_message == ARRIVAL_TOKEN
        player_input = player_message
        if is_arrival:
            player_input = await _build_arrival_message(conn, snapshot)

        builder = ContextBuilder(ctx.pool, snapshot.id)
        context = await builder.build(
            conn=conn,
            player_input=player_input,
            current_cycle=snapshot.current_cycle,
            current_time=snapshot.current_time,
            current_location_name=current_location,
        )
    return Prepared(player_input=player_input, player_message=player_message,
                    is_arrival=is_arrival, context=context, pending_roll=pending_roll)
