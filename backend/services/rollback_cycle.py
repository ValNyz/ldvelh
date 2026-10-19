"""Legacy cycle-based rollback, kept one release behind ROLLBACK_ENGINE=cycle (#22)."""

import logging
from uuid import UUID

from repos import turns
from schema import EngineType
from services.engine import get_engine
from services.rollback import RollbackPlan
from utils.json_utils import parse_json

logger = logging.getLogger(__name__)


def _stored_info_requests(narrator_deltas) -> list[str]:
    """The detail requests a stored turn left behind; none for messages saved before #64."""
    if isinstance(narrator_deltas, str):
        narrator_deltas = parse_json(narrator_deltas)
    if not isinstance(narrator_deltas, dict):
        return []
    return [r for r in narrator_deltas.get("info_requests") or [] if isinstance(r, str)]


async def undo_by_cycle(
    conn, game_id: UUID, plan: RollbackPlan, reader, populator
) -> dict:
    """Legacy cycle-based rollback, kept one release behind ROLLBACK_ENGINE=cycle (#22).

    Deletes the plan's messages, reverses their credit deltas, resets the game state from
    the last remaining assistant message, deletes the KG rows of later cycles and restores
    the engine state from that message's snapshot."""
    messages_to_delete = plan.messages_to_delete
    target_cycle = plan.target_cycle
    ids_to_delete = [m["id"] for m in messages_to_delete]
    deleted_ids = set(ids_to_delete)
    # The plan deletes a suffix: the kept messages are all the others.
    kept = [
        m
        for m in await reader.get_messages(conn, order="asc")
        if m["id"] not in deleted_ids
    ]

    # Reverse credit deltas from messages being deleted
    credit_reversal = 0
    for m in messages_to_delete:
        deltas = m.get("narrator_deltas")
        if deltas:
            if isinstance(deltas, str):
                deltas = parse_json(deltas)
            if isinstance(deltas, dict):
                cd = deltas.get("credit_delta")
                # A refused debit never touched the balance; rows from before
                # the "applied" key existed count as applied.
                if cd and isinstance(cd, dict) and cd.get("applied") is not False:
                    credit_reversal -= cd.get("amount", 0)

    # Restore full game state from last remaining assistant message
    restore_date = None
    restore_time = None
    restore_location_id = None
    restore_requests: list[str] = []
    engine_snapshot = None
    for m in reversed(kept):
        if m["role"] == "assistant":
            restore_date = m.get("game_date")
            restore_time = m.get("time")
            restore_location_id = m.get("location_id")
            restore_requests = _stored_info_requests(m.get("narrator_deltas"))
            # Not part of get_messages (never sent to the client).
            engine_snapshot = await reader.get_message_engine_snapshot(conn, m["id"])
            break

    # All-or-nothing: a failure part-way must not leave messages deleted
    # and credits refunded while the KG still holds the later cycle (#11).
    async with conn.transaction():
        # First statement: waits for a background write holding a deleted message
        # FOR SHARE (#23) before this transaction locks anything else.
        await conn.execute(
            "DELETE FROM messages WHERE id = ANY($1)",
            ids_to_delete,
        )

        if credit_reversal != 0:
            await conn.execute(
                "UPDATE protagonists SET credits = credits + $1 WHERE game_id = $2",
                credit_reversal,
                game_id,
            )

        # Reset game state (current location included) before the KG delete,
        # so the game no longer points at locations about to be removed.
        await conn.execute(
            """UPDATE games
               SET current_cycle = $2,
                   "current_date" = $3,
                   "current_time" = $4,
                   current_location_id = $5,
                   detail_requests = $6,
                   last_extraction_time = NULL,
                   updated_at = NOW()
               WHERE id = $1""",
            game_id,
            target_cycle,
            restore_date,
            restore_time,
            restore_location_id,
            restore_requests,
        )

        rollback_result = await populator.rollback_to_cycle(conn, target_cycle)
        # The deleted turns' journal goes with them; abandoned open turns are purged too (#105).
        await turns.delete_turns(conn, game_id, plan.turn_ids)
        await turns.expire_pending_rolls(conn, game_id)

        game = await reader.get_game(conn)
        engine_type = EngineType(game["engine"]) if game else EngineType.NONE
        if engine_type != "none":
            if engine_snapshot is not None:  # {} is a valid empty turn state
                engine = get_engine(engine_type)
                await engine.restore_turn_state(conn, game_id, engine_snapshot)
            else:  # legacy message saved before snapshots: engine state is kept
                logger.warning(
                    f"[ROLLBACK] No engine snapshot for game {game_id}, "
                    "engine state kept"
                )

    return rollback_result
