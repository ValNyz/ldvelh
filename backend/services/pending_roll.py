"""The game's roll waiting for an aspect invocation, with what the player may spend (#32)."""

from uuid import UUID

from domain.turn import PendingRoll
from repos import turns
from services.engine.base import BaseEngine


async def load_pending_roll(conn, game_id: UUID, engine: BaseEngine) -> PendingRoll | None:
    """The stored roll plus the character's current aspects and fate points, or None."""
    row = await turns.get_pending_roll(conn, game_id)
    if row is None:
        return None
    offer = engine.available_invocations(await engine.get_stats(conn, game_id))
    return PendingRoll(
        id=row["id"],
        roll=row["roll"],
        player_message=row["player_message"],
        aspects=offer.aspects,
        fate_points=offer.fate_points,
    )
