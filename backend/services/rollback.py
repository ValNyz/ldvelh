"""Rollback by replaying the turn journal (#22).

A rollback deletes a message and every message after it, then undoes the world writes of
their turns with world_changes_undo (#105): whatever a turn wrote (narration, deltas, roll,
extraction, Director) is put back exactly as it was before the turn.
"""

from dataclasses import dataclass
from uuid import UUID

from repos import turns


@dataclass(frozen=True)
class RollbackPlan:
    """What a rollback removes: the messages, the cycle it goes back to, their turns."""

    messages_to_delete: list[dict]
    target_cycle: int
    turn_ids: list[UUID]  # distinct, not null, in message order
    has_legacy_message: bool  # a message saved before the journal (turn_id NULL)


def _cutoff(
    messages: list[dict], message_id: UUID | None, keep_until_index: int | None
) -> int | None:
    """Index of the first message to delete, None when the target is unknown."""
    if message_id:
        return next(
            (i for i, m in enumerate(messages) if str(m["id"]) == str(message_id)), None
        )
    return keep_until_index


def plan_rollback(
    messages: list[dict], message_id: UUID | None, keep_until_index: int | None
) -> RollbackPlan | None:
    """The rollback of `messages` (ascending) from `message_id`, or from `keep_until_index`
    (legacy); None when there is nothing to delete."""
    # Imported here: game_service imports this module.
    from services.game_service import RollbackRejected

    keep_until_index = _cutoff(messages, message_id, keep_until_index)
    if keep_until_index is None or keep_until_index >= len(messages):
        return None
    messages_to_delete = messages[keep_until_index:]
    if not messages_to_delete:
        return None
    # The arrival pair (protocol token + first narration) is never rolled back:
    # doing so would target cycle 0 and wipe the initial world (#11).
    if keep_until_index < 2:
        raise RollbackRejected(RollbackRejected.ARRIVAL_SCENE)
    turn_ids = list(
        dict.fromkeys(m["turn_id"] for m in messages_to_delete if m["turn_id"])
    )
    return RollbackPlan(
        messages_to_delete=messages_to_delete,
        target_cycle=messages[keep_until_index - 1]["cycle"],
        turn_ids=turn_ids,
        has_legacy_message=any(m["turn_id"] is None for m in messages_to_delete),
    )


async def _resumed_halted_turns(conn, turn_ids: list[UUID]) -> list[UUID]:
    """Open turns whose pending roll one of `turn_ids` resumed (claim_pending_roll moved
    the roll to the resuming turn). The halted turn holds the roll's insert: the action
    began there, so undoing the resuming turn undoes it too (#32, #134)."""
    rows = await conn.fetch(
        """SELECT DISTINCT t.id FROM world_changes wc
           JOIN turns t ON t.id = (wc.old_row ->> 'turn_id')::uuid
           WHERE wc.turn_id = ANY($1) AND wc.table_name = 'mechanic_rolls' AND wc.op = 'U'
             AND t.status = 'open'""",
        turn_ids,
    )
    return [r["id"] for r in rows]


async def _undo_changes(conn, turn_ids: list[UUID]) -> int:
    """Replay the turns' journal backwards; returns the number of changes undone."""
    return await conn.fetchval("SELECT world_changes_undo($1)", turn_ids)


async def undo_turns(conn, game_id: UUID, plan: RollbackPlan) -> dict:
    """Delete the plan's messages and undo their turns' writes, all or nothing."""
    # Imported here: game_service imports this module.
    from services.game_service import RollbackRejected

    if plan.has_legacy_message:
        raise RollbackRejected(RollbackRejected.BEFORE_JOURNAL)
    async with conn.transaction():
        # First statement: waits for a background write holding a deleted message
        # FOR SHARE (#23) before this transaction locks anything else. Also before the
        # undo: a chronology row it removes must no longer be referenced by a message.
        await conn.execute(
            "DELETE FROM messages WHERE id = ANY($1)",
            [m["id"] for m in plan.messages_to_delete],
        )
        undone = await _undo_changes(
            conn, plan.turn_ids + await _resumed_halted_turns(conn, plan.turn_ids)
        )
        # After the undo: a restored row may point at a turn deleted here (a roll back on
        # its halted turn); the undo checks its foreign keys while those turns still
        # exist, then deleting them sets the references NULL.
        deleted = await turns.delete_turns(conn, game_id, plan.turn_ids)
        await turns.expire_pending_rolls(conn, game_id)
        await conn.execute("UPDATE games SET updated_at = now() WHERE id = $1", game_id)
    return {"undone_changes": undone, "deleted_turns": deleted}
