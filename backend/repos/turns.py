"""Turn repository: the SQL of a narration turn's own rows (messages, rolls, turns), on
the caller's connection.

No function opens its own connection or transaction: the commit step runs them all
in one transaction, so a failure anywhere leaves nothing behind (#20). What the narration
changes in the world is applied by services/turn_effects.py.
"""

from uuid import UUID

from domain.turn import NarrationState
from schema.engine import RollResult
from utils.json_utils import parse_json


async def store_info_requests(conn, game_id: UUID, requests: list[str]) -> None:
    """The details the next turn's context loads, replacing the previous set (one turn only)."""
    await conn.execute(
        "UPDATE games SET detail_requests = $1 WHERE id = $2", requests, game_id
    )


async def create_conversation(conn, game_id: UUID, start_cycle: int) -> UUID:
    return await conn.fetchval(
        "INSERT INTO conversations (game_id, start_cycle) VALUES ($1, $2) RETURNING id",
        game_id,
        start_cycle,
    )


async def active_conversation(conn, game_id: UUID) -> UUID | None:
    return await conn.fetchval(
        "SELECT id FROM conversations"
        " WHERE game_id = $1 AND compacted = false"
        " ORDER BY created_at DESC LIMIT 1",
        game_id,
    )


async def save_message(
    conn,
    game_id: UUID,
    conversation_id: UUID,
    role: str,
    content: str,
    sequence: int,
    cycle: int | None = None,
    time: str | None = None,
    game_date: str | None = None,
    location_id: UUID | None = None,
    narrator_deltas: dict | None = None,
    engine_snapshot: dict | None = None,
    narrator_context: list | None = None,
    turn_id: UUID | None = None,
) -> UUID:
    """Save a message in a conversation; `location_id`: the place of the turn."""
    return await conn.fetchval(
        """INSERT INTO messages (
            game_id, conversation_id, role, content,
            cycle, game_date, time, location_id, sequence,
            narrator_deltas, engine_snapshot, narrator_context, turn_id
        ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13) RETURNING id""",
        game_id,
        conversation_id,
        role,
        content,
        cycle,
        game_date,
        time,
        location_id,
        sequence,
        narrator_deltas,
        engine_snapshot,
        narrator_context,
        turn_id,
    )


async def save_turn_messages(
    conn,
    game_id: UUID,
    *,
    user_message: str,
    assistant_message: str,
    state: NarrationState,
    narrator_deltas: dict,
    engine_snapshot: dict | None,
    turn_id: UUID | None,
) -> tuple[UUID, UUID]:
    """User + assistant message pair of the turn; returns (user_id, assistant_id).

    `state`: its place resolved (the commit's, or services.turn_effects.resolve_place);
    a place left unresolved raises ValueError rather than stamping no location.
    `turn_id`: the turn the pair belongs to (None outside a turn: tests, fixtures)."""
    if not state.location_resolved and state.location and state.location.strip():
        raise ValueError(
            "the state's place is not resolved (turn_effects.resolve_place)"
        )
    conv_id = await active_conversation(conn, game_id)
    if not conv_id:
        conv_id = await create_conversation(conn, game_id, state.cycle)

    max_seq = await conn.fetchval(
        "SELECT COALESCE(MAX(sequence), 0) FROM messages WHERE conversation_id = $1",
        conv_id,
    )
    stamp = {
        "cycle": state.cycle,
        "time": state.time,
        "game_date": state.date,
        # The place was resolved (and counted) once: never again here.
        "location_id": state.location_id,
    }
    user_id = await save_message(
        conn,
        game_id,
        conv_id,
        "user",
        user_message,
        sequence=max_seq + 1,
        turn_id=turn_id,
        **stamp,
    )
    assistant_id = await save_message(
        conn,
        game_id,
        conv_id,
        "assistant",
        assistant_message,
        sequence=max_seq + 2,
        **stamp,
        narrator_deltas=narrator_deltas,
        engine_snapshot=engine_snapshot,
        turn_id=turn_id,
    )
    return user_id, assistant_id


async def open_turn(conn, game_id: UUID) -> UUID:
    """A new open turn of the game; its world writes are journaled under its id (#105)."""
    return await conn.fetchval(
        "INSERT INTO turns (game_id) VALUES ($1) RETURNING id", game_id
    )


async def mark_committed(conn, turn_id: UUID) -> None:
    """The turn's writes are saved: it becomes a rollback target."""
    await conn.execute(
        "UPDATE turns SET status = 'committed', committed_at = now() WHERE id = $1",
        turn_id,
    )


async def delete_turns(conn, game_id: UUID, turn_ids: list[UUID]) -> int:
    """Delete the game's listed turns and its open turns (abandoned ones), with their
    journal and extraction logs; their messages and rolls are kept with turn_id NULL.
    Returns the number of turns deleted."""
    result = await conn.execute(
        "DELETE FROM turns WHERE game_id = $1 AND (id = ANY($2) OR status = 'open')",
        game_id,
        turn_ids,
    )
    return int(result.split()[-1])


async def lock_engine(conn, game_id: UUID) -> None:
    """The engine is immutable once the first narration turn is saved."""
    await conn.execute(
        "UPDATE games SET engine_locked = TRUE, updated_at = NOW() WHERE id = $1",
        game_id,
    )


async def log_mechanic_roll(
    conn,
    game_id: UUID,
    *,
    message_id: UUID,
    engine: str,
    roll: RollResult,
    cycle: int | None,
    turn_id: UUID | None,
) -> UUID:
    """Log a resolved roll with the assistant message that narrated it, under its turn."""
    return await conn.fetchval(
        """INSERT INTO mechanic_rolls
           (game_id, message_id, engine, skill_used,
            roll_details, outcome, complication, cycle, turn_id)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
           RETURNING id""",
        game_id,
        message_id,
        engine,
        roll.details.get("skill_name"),
        roll.model_dump(),
        roll.outcome,
        roll.complication,
        cycle,
        turn_id,
    )


async def store_pending_roll(
    conn,
    game_id: UUID,
    roll: RollResult,
    player_message: str,
    cycle: int,
    turn_id: UUID | None,
) -> UUID:
    """A failed Fate roll waiting for an aspect invocation (at most one per game), stored
    under the turn it halted."""
    # Only Fate Core pauses a roll for an invocation.
    return await conn.fetchval(
        """INSERT INTO mechanic_rolls
           (game_id, message_id, engine, skill_used, roll_details, outcome, complication,
            cycle, status, player_message, turn_id)
           VALUES ($1, NULL, 'fate_core', $2, $3, $4, $5, $6, 'pending', $7, $8)
           RETURNING id""",
        game_id,
        roll.details.get("skill_name"),
        roll.model_dump(),
        roll.outcome,
        roll.complication,
        cycle,
        player_message,
        turn_id,
    )


async def get_pending_roll(conn, game_id: UUID) -> dict | None:
    """The game's roll waiting for an invocation: {"id", "roll", "player_message"}."""
    row = await conn.fetchrow(
        """SELECT id, roll_details, player_message FROM mechanic_rolls
        WHERE game_id = $1 AND status = 'pending'""",
        game_id,
    )
    if not row:
        return None
    roll = row["roll_details"]
    if isinstance(roll, str):
        roll = parse_json(roll)
    return {
        "id": row["id"],
        "roll": roll,
        "player_message": row["player_message"] or "",
    }


async def claim_pending_roll(
    conn,
    game_id: UUID,
    roll_id: UUID,
    roll_details: dict,
    outcome: str,
    message_id: UUID,
    cycle: int,
    turn_id: UUID | None,
) -> bool:
    """Resolve the pending roll with its final details; False if it was no longer pending.

    The roll is stored pending at the cycle before its turn (the narration, hence a possible
    day change, does not exist yet): resolving re-stamps it with the turn's post-turn cycle,
    like the turn's messages, so rolling the turn back removes it (#134). It also moves to
    the resuming turn (#105)."""
    claimed = await conn.fetchval(
        """UPDATE mechanic_rolls
        SET status = 'resolved', roll_details = $3, outcome = $4, message_id = $5, cycle = $6,
            turn_id = $7
        WHERE id = $1 AND game_id = $2 AND status = 'pending'
        RETURNING id""",
        roll_id,
        game_id,
        roll_details,
        outcome,
        message_id,
        cycle,
        turn_id,
    )
    return claimed is not None


async def pending_roll_turn(conn, roll_id: UUID) -> UUID | None:
    """The turn a roll is stored under (the halted turn while it is pending)."""
    return await conn.fetchval(
        "SELECT turn_id FROM mechanic_rolls WHERE id = $1", roll_id
    )


# Every (table, column) referencing turns(id), world_changes first: deleting the turn
# cascades to it. The identity columns are journaled: a halted turn writes no identity row
# today, so their UPDATE matches nothing; if one ever did, undoing the resuming turn would
# restore the deleted halted turn's id (a deferred FK error at the end of the replay).
_TURN_REFERENCES = (
    ("world_changes", "turn_id"),
    ("messages", "turn_id"),
    ("mechanic_rolls", "turn_id"),
    ("extraction_logs", "turn_id"),
    ("director_commitments", "turn_id"),
    ("llm_calls", "turn_id"),
    ("entity_registry", "created_turn_id"),
    ("entity_aliases", "turn_id"),
    ("entity_mentions", "turn_id"),
    ("entity_merges", "turn_id"),
    ("identity_events", "turn_id"),
)


async def adopt_halted_turn(
    conn, game_id: UUID, halted_turn_id: UUID | None, turn_id: UUID
) -> bool:
    """The turn resuming a pending roll takes over the halted turn that stored it (#22).

    The halted turn's journal (the roll's insert) and every row pointing at it move to
    `turn_id`, then the halted turn is deleted: undoing the resuming turn removes the roll
    whole, and no later rollback purges the halted turn's journal as an abandoned open turn.
    The moved journal rows keep their ids, older than the resuming turn's, so the undo still
    replays them last. False when `halted_turn_id` is not another open turn of the game."""
    if halted_turn_id is None or halted_turn_id == turn_id:
        return False
    halted = await conn.fetchval(
        "SELECT id FROM turns WHERE id = $1 AND game_id = $2 AND status = 'open' FOR UPDATE",
        halted_turn_id,
        game_id,
    )
    if halted is None:
        return False
    for table, column in _TURN_REFERENCES:
        await conn.execute(
            f"UPDATE {table} SET {column} = $2 WHERE {column} = $1",
            halted_turn_id,
            turn_id,
        )
    await conn.execute("DELETE FROM turns WHERE id = $1", halted_turn_id)
    return True


async def expire_pending_rolls(conn, game_id: UUID) -> None:
    """A rollback discards the action a pending roll belongs to: it never comes back (#32)."""
    await conn.execute(
        "UPDATE mechanic_rolls SET status = 'expired' WHERE game_id = $1 AND status = 'pending'",
        game_id,
    )
