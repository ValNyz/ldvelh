"""The game's Fate roll waiting for an aspect invocation, with what the player may spend (#32)."""

from uuid import UUID

from domain.turn import PendingRoll
from repos import turns
from services.engine.base import BaseEngine
from services.engine.fate_core import aspect_names


async def load_pending_roll(conn, game_id: UUID, engine: BaseEngine,
                            engine_stats: dict | None = None) -> PendingRoll | None:
    """The stored roll plus the character's current aspects and fate points, or None.

    `engine_stats` (full sheet) avoids reloading it when the caller already has it.
    """
    row = await turns.get_pending_roll(conn, game_id)
    if row is None:
        return None
    if engine_stats is None:
        engine_stats = await engine.get_stats(conn, game_id)
    return PendingRoll(
        id=row["id"],
        roll=row["roll"],
        player_message=row["player_message"],
        aspects=aspect_names(engine_stats),
        fate_points=(engine_stats or {}).get("fate_points", 0),
    )
