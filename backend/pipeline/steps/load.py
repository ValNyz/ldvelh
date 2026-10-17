"""Load step: the player's input (arrival text substituted) and the narration context."""

import logging
from dataclasses import dataclass

import asyncpg

from domain.game import GameSnapshot
from kg.reader import KnowledgeGraphReader
from pipeline.context import TurnContext
from schema.narration import NarrationContext
from services.context_builder import ContextBuilder

logger = logging.getLogger(__name__)

ARRIVAL_TOKEN = "__ARRIVEE__"
DEFAULT_ARRIVAL_MESSAGE = "Je viens d'arriver."


@dataclass(frozen=True)
class Prepared:
    player_input: str
    is_arrival: bool
    context: NarrationContext


async def _build_arrival_message(pool: asyncpg.Pool, snapshot: GameSnapshot) -> str:
    """Player message for the arrival turn, from the game's genre arrival_prompt."""
    if not snapshot.genre_id:
        return DEFAULT_ARRIVAL_MESSAGE
    reader = KnowledgeGraphReader(pool, snapshot.id)
    async with pool.acquire() as conn:
        genre = await reader.get_genre(conn, snapshot.genre_id)
    if not genre or not genre.get("arrival_prompt"):
        return DEFAULT_ARRIVAL_MESSAGE
    return (
        genre["arrival_prompt"]
        .replace("{world_name}", snapshot.world_name or "")
        .replace("{protagonist_name}", snapshot.protagonist_name or "")
    )


async def load_turn(ctx: TurnContext) -> Prepared:
    snapshot = ctx.snapshot
    # The old DTO dropped None values, so a missing location read as "".
    current_location = snapshot.current_location_name or ""
    mode_label = "LIGHT" if current_location else "FIRST_LIGHT"
    logger.info(f"[CHAT] Mode: {mode_label}, Cycle: {snapshot.current_cycle}")

    # Protocol token (__ARRIVEE__): replace it with the genre's arrival text.
    # genre_id / world_name / protagonist_name come from the snapshot (#9).
    is_arrival = ctx.request.message == ARRIVAL_TOKEN
    player_input = ctx.request.message
    if is_arrival:
        player_input = await _build_arrival_message(ctx.pool, snapshot)

    async with ctx.pool.acquire() as conn:
        builder = ContextBuilder(ctx.pool, snapshot.id)
        context = await builder.build(
            conn=conn,
            player_input=player_input,
            current_cycle=snapshot.current_cycle,
            current_time=snapshot.current_time,
            current_location_name=current_location,
        )
    return Prepared(player_input=player_input, is_arrival=is_arrival, context=context)
