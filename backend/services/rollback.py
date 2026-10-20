"""Rollback by replaying the turn journal (#22).

A rollback deletes a message and every message after it, then undoes the world writes of
their turns with world_changes_undo (#105): whatever a turn wrote (narration, deltas, roll,
extraction, Director) is put back exactly as it was before the turn.
"""

from dataclasses import dataclass
from uuid import UUID

from domain.errors import RollbackRejected
from repos import turns


@dataclass(frozen=True)
class RollbackPlan:
    """What a rollback removes: the messages, the cycle it goes back to, their turns."""

    messages_to_delete: list[dict]
    target_cycle: int
    turn_ids: list[UUID]  # distinct, not null, in message order
    has_legacy_message: bool  # a message saved before the journal (turn_id NULL)


def _cutoff(messages: list[dict], message_id: UUID | None) -> int | None:
    """Index of the first message to delete, None when the target is unknown."""
    if not message_id:
        return None
    return next(
        (i for i, m in enumerate(messages) if str(m["id"]) == str(message_id)), None
    )


def plan_rollback(messages: list[dict], message_id: UUID | None) -> RollbackPlan | None:
    """The rollback of `messages` (ascending) from `message_id`; None when there is
    nothing to delete."""
    keep_until_index = _cutoff(messages, message_id)
    if keep_until_index is None:
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


async def _repair_resumed_rolls(
    conn, game_id: UUID, turn_ids: list[UUID]
) -> list[UUID]:
    """The resumes among `turn_ids`, found by their claim: a mechanic_rolls U whose old
    turn_id is the halted turn that stored the roll. Returns the rolls the undo cannot
    remove.

    - Halted turn still open (a resume committed before the adoption, P5a games): adopted
      now, as the commit does today, so the undo removes the roll with its insert.
    - Halted turn gone: either adopted at commit (every resume since P5b: the roll's
      insert moved to the resuming turn) or purged by an earlier rollback with the roll's
      insert (P5a games). The roll is returned in both cases; in the first one the undo
      would have removed it anyway."""
    rows = await conn.fetch(
        """SELECT DISTINCT turn_id, row_id, old_row ->> 'turn_id' AS halted
           FROM world_changes
           WHERE turn_id = ANY($1) AND table_name = 'mechanic_rolls' AND op = 'U'
             AND old_row ->> 'turn_id' IS NOT NULL""",
        turn_ids,
    )
    orphaned = []
    for r in rows:
        halted = UUID(r["halted"])
        if await turns.adopt_halted_turn(conn, game_id, halted, r["turn_id"]):
            continue
        if await conn.fetchval("SELECT 1 FROM turns WHERE id = $1", halted):
            continue
        orphaned.append(r["row_id"])
    return orphaned


async def _undo_changes(conn, turn_ids: list[UUID]) -> int:
    """Replay the turns' journal backwards; returns the number of changes undone."""
    return await conn.fetchval("SELECT world_changes_undo($1)", turn_ids)


async def undo_turns(conn, game_id: UUID, plan: RollbackPlan) -> dict:
    """Delete the plan's messages and undo their turns' writes, all or nothing."""
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
        # A roll pending now belongs to an open turn purged below: expire it (R12) before
        # the undo, which may put an older roll back to pending (one per game).
        await turns.expire_pending_rolls(conn, game_id)
        orphaned_rolls = await _repair_resumed_rolls(conn, game_id, plan.turn_ids)
        if orphaned_rolls:
            # Before the undo: with no insert left to undo, it could only put these rolls
            # back to pending (one per game, not deferrable: two of them fail) and never
            # remove them. Deleted now, their claim's U finds no row, so it cannot restore
            # a turn_id pointing at the purged halted turn either.
            await conn.execute(
                "DELETE FROM mechanic_rolls WHERE id = ANY($1) AND game_id = $2",
                orphaned_rolls,
                game_id,
            )
        undone = await _undo_changes(conn, plan.turn_ids)
        # After the undo: a restored row may point at a turn deleted here; the undo checks
        # its foreign keys while those turns still exist, then deleting them sets the
        # references NULL.
        deleted = await turns.delete_turns(conn, game_id, plan.turn_ids)
        await turns.expire_pending_rolls(conn, game_id)
        await conn.execute("UPDATE games SET updated_at = now() WHERE id = $1", game_id)
    return {"undone_changes": undone, "deleted_turns": deleted}
