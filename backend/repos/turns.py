"""Turn repository: every write of a narration turn, on the caller's connection.

No function opens its own connection or transaction: the commit step runs them all
in one transaction, so a failure anywhere leaves nothing behind (#20).
"""

import logging
from uuid import UUID

from config import get_settings
from domain.turn import AppliedCredit, AppliedDeltas, NarrationState
from kg.populator import KnowledgeGraphPopulator
from kg.reader import KnowledgeGraphReader
from repos import entities as entity_repo
from schema import DEFAULT_GAME_TIME
from schema.engine import RollResult
from schema.narration import NarrationOutput
from utils.json_utils import parse_json
from utils.log_safe import log_cause

logger = logging.getLogger(__name__)


def _populator(game_id: UUID) -> KnowledgeGraphPopulator:
    # Built without a pool: the methods used here only take `conn`.
    return KnowledgeGraphPopulator(None, game_id)


async def _resolve_location(conn, game_id: UUID, location: str, new_cycle: int) -> UUID | None:
    """Id of the narrated location (find_entity), created as a stub when unknown. A name
    that is ambiguous, or that an existing location holds as its label alongside another
    one's alias, never creates a duplicate."""
    target = await entity_repo.find_for_upsert(conn, game_id, location, "location")
    if target.entity_id:
        old_id = await conn.fetchval(
            "SELECT current_location_id FROM games WHERE id = $1", game_id
        )
        if old_id != target.entity_id:
            # Ids only: a location name is story text.
            logger.info(f"[GAME] Location changed: {old_id} → {target.entity_id}")
        return target.entity_id
    if target.ambiguous:
        return None
    # Create a stub location (will be fully populated during extraction)
    location_id = await conn.fetchval(
        """INSERT INTO locations (game_id, name, created_cycle)
        VALUES ($1, $2, $3)
        RETURNING id""",
        game_id, location, new_cycle,
    )
    logger.info(
        f"[GAME] Created stub location {location_id} "
        f"(cycle {new_cycle}), to be enriched during extraction"
    )
    return location_id


async def apply_narration_state(conn, game_id: UUID, narration: NarrationOutput,
                                current_cycle: int) -> NarrationState:
    """Cycle, date, time and location from the narration; stub events and locations."""
    new_cycle = current_cycle + 1 if narration.day_transition else current_cycle
    reader = KnowledgeGraphReader(None, game_id)
    # An unusable narrator time is None (schema/core.py GameTime): keep the game's time.
    # Read here, in the commit transaction, so it is the stored value, not a turn-start copy.
    new_time = narration.time.new_time if narration.time else None
    if new_time is None:
        new_time = await reader.get_current_time(conn) or DEFAULT_GAME_TIME
    location = narration.current_location
    populator = _populator(game_id)

    current_date = await reader.get_current_date(conn)
    new_date = current_date
    if narration.day_transition:
        new_date = narration.day_transition.new_date
        if not new_date:
            new_date = f"Jour {new_cycle}"
            logger.warning(f"[GAME] day_transition without new_date, using '{new_date}'")

    location_id = None
    if location:
        location_id = await _resolve_location(conn, game_id, location, new_cycle)

    for evt in narration.events_mentioned:
        await populator.create_stub_event(conn, evt, new_cycle)

    await populator.update_game_state(
        conn, cycle=new_cycle, date=new_date, time=new_time, location_id=location_id,
    )

    return NarrationState(
        cycle=new_cycle,
        time=new_time,
        location=location,
        npcs_present=narration.npcs_present or [],
        date=new_date,
    )


async def _apply_compel(conn, game_id: UUID, narration: NarrationOutput) -> dict | None:
    """Fate Core compel: +1 fate point if accepted, -1 (floor 0) if refused."""
    if narration.compel_result not in ("accepted", "refused"):
        return None
    try:
        # Savepoint: a failed statement must not abort the turn's transaction.
        async with conn.transaction():
            fp = await conn.fetchval(
                "SELECT fate_points FROM character_fate WHERE game_id = $1", game_id)
            if fp is None:
                return None
            accepted = narration.compel_result == "accepted"
            new_fp = fp + 1 if accepted else max(0, fp - 1)
            await conn.execute(
                "UPDATE character_fate SET fate_points = $1 WHERE game_id = $2", new_fp, game_id)
    except Exception as e:
        log_cause(logger, logging.WARNING, "[COMPEL] FP adjustment failed", e,
                  debug_detail=get_settings().log_prompts)
        return None
    return {
        "result": narration.compel_result,
        "aspect": narration.compel_aspect,
        "fp_change": 1 if accepted else -1,
        "new_fp": new_fp,
    }


async def apply_narrator_deltas(conn, game_id: UUID, narration: NarrationOutput,
                                cycle: int) -> AppliedDeltas:
    """Credit delta, entity reveals and compel, applied on the spot."""
    populator = _populator(game_id)
    credit = None
    if narration.credit_delta:
        cd = narration.credit_delta
        applied, new_balance, error = await populator.credit_transaction(
            conn, cd.amount, cycle, cd.description
        )
        credit = AppliedCredit(amount=cd.amount, description=cd.description, applied=applied,
                               new_balance=new_balance, error=error)

    for reveal in narration.entity_reveals:
        if reveal.entity_type == "character":
            await populator.mark_character_known(conn, reveal.current_name, reveal.real_name)
        elif reveal.entity_type == "location":
            await populator.mark_location_accessible(conn, reveal.current_name)

    return AppliedDeltas(credit=credit, compel=await _apply_compel(conn, game_id, narration))


async def store_info_requests(conn, game_id: UUID, requests: list[str]) -> None:
    """The details the next turn's context loads, replacing the previous set (one turn only)."""
    await conn.execute("UPDATE games SET detail_requests = $1 WHERE id = $2", requests, game_id)


async def save_turn_messages(conn, game_id: UUID, *, user_message: str, assistant_message: str,
                             state: NarrationState, narrator_deltas: dict,
                             engine_snapshot: dict | None,
                             turn_id: UUID | None) -> tuple[UUID, UUID]:
    """User + assistant message pair of the turn; returns (user_id, assistant_id).

    `turn_id`: the turn the pair belongs to (None outside a turn: tests, fixtures)."""
    populator = _populator(game_id)
    conv_id = await populator.get_active_conversation(conn)
    if not conv_id:
        conv_id = await populator.create_conversation(conn, state.cycle)

    max_seq = await conn.fetchval(
        "SELECT COALESCE(MAX(sequence), 0) FROM messages WHERE conversation_id = $1", conv_id,
    )
    stamp = {"cycle": state.cycle, "time": state.time, "game_date": state.date,
             "location_ref": state.location}
    user_id = await populator.save_message(
        conn, conv_id, "user", user_message, sequence=max_seq + 1, turn_id=turn_id, **stamp,
    )
    assistant_id = await populator.save_message(
        conn, conv_id, "assistant", assistant_message, sequence=max_seq + 2, **stamp,
        narrator_deltas=narrator_deltas, engine_snapshot=engine_snapshot, turn_id=turn_id,
    )
    return user_id, assistant_id


async def open_turn(conn, game_id: UUID) -> UUID:
    """A new open turn of the game; its world writes are journaled under its id (#105)."""
    return await conn.fetchval("INSERT INTO turns (game_id) VALUES ($1) RETURNING id", game_id)


async def mark_committed(conn, turn_id: UUID) -> None:
    """The turn's writes are saved: it becomes a rollback target."""
    await conn.execute(
        "UPDATE turns SET status = 'committed', committed_at = now() WHERE id = $1", turn_id)


async def delete_turns(conn, game_id: UUID, turn_ids: list[UUID]) -> int:
    """Delete the game's listed turns and its open turns (abandoned ones), with their
    journal and extraction logs; their messages and rolls are kept with turn_id NULL.
    Returns the number of turns deleted."""
    result = await conn.execute(
        "DELETE FROM turns WHERE game_id = $1 AND (id = ANY($2) OR status = 'open')",
        game_id, turn_ids,
    )
    return int(result.split()[-1])


async def hold_source_message(conn, message_id: UUID) -> bool:
    """True if the message exists; it then stays share-locked until the transaction ends,
    so a rollback deleting it waits for the caller's writes (#23)."""
    return await conn.fetchval(
        "SELECT 1 FROM messages WHERE id = $1 FOR SHARE", message_id) is not None


async def lock_engine(conn, game_id: UUID) -> None:
    """The engine is immutable once the first narration turn is saved."""
    await _populator(game_id).lock_engine(conn)


async def log_mechanic_roll(conn, game_id: UUID, *, message_id: UUID, engine: str,
                            roll: RollResult, cycle: int | None, turn_id: UUID | None) -> UUID:
    """Log a resolved roll with the assistant message that narrated it, under its turn."""
    return await _populator(game_id).log_mechanic_roll(
        conn, game_id, message_id, engine, roll.details.get("skill_name"),
        roll.model_dump(), roll.outcome, roll.complication, cycle, turn_id,
    )


async def store_pending_roll(conn, game_id: UUID, roll: RollResult, player_message: str,
                             cycle: int, turn_id: UUID | None) -> UUID:
    """A failed Fate roll waiting for an aspect invocation (at most one per game), stored
    under the turn it halted."""
    # Only Fate Core pauses a roll for an invocation.
    return await conn.fetchval(
        """INSERT INTO mechanic_rolls
           (game_id, message_id, engine, skill_used, roll_details, outcome, complication,
            cycle, status, player_message, turn_id)
           VALUES ($1, NULL, 'fate_core', $2, $3, $4, $5, $6, 'pending', $7, $8)
           RETURNING id""",
        game_id, roll.details.get("skill_name"), roll.model_dump(), roll.outcome,
        roll.complication, cycle, player_message, turn_id,
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
    return {"id": row["id"], "roll": roll, "player_message": row["player_message"] or ""}


async def claim_pending_roll(conn, game_id: UUID, roll_id: UUID, roll_details: dict,
                             outcome: str, message_id: UUID, cycle: int,
                             turn_id: UUID | None) -> bool:
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
        roll_id, game_id, roll_details, outcome, message_id, cycle, turn_id,
    )
    return claimed is not None


async def pending_roll_turn(conn, roll_id: UUID) -> UUID | None:
    """The turn a roll is stored under (the halted turn while it is pending)."""
    return await conn.fetchval("SELECT turn_id FROM mechanic_rolls WHERE id = $1", roll_id)


# Every (table, column) referencing turns(id), world_changes first: deleting the turn
# cascades to it. The identity columns are journaled: a halted turn writes no identity row
# today, so their UPDATE matches nothing; if one ever did, undoing the resuming turn would
# restore the deleted halted turn's id (a deferred FK error at the end of the replay).
_TURN_REFERENCES = (
    ("world_changes", "turn_id"), ("messages", "turn_id"), ("mechanic_rolls", "turn_id"),
    ("extraction_logs", "turn_id"), ("director_commitments", "turn_id"),
    ("llm_calls", "turn_id"), ("entity_registry", "created_turn_id"),
    ("entity_aliases", "turn_id"), ("entity_mentions", "turn_id"),
    ("entity_merges", "turn_id"), ("identity_events", "turn_id"),
)


async def adopt_halted_turn(conn, game_id: UUID, halted_turn_id: UUID | None,
                            turn_id: UUID) -> bool:
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
        halted_turn_id, game_id,
    )
    if halted is None:
        return False
    for table, column in _TURN_REFERENCES:
        await conn.execute(f"UPDATE {table} SET {column} = $2 WHERE {column} = $1",
                           halted_turn_id, turn_id)
    await conn.execute("DELETE FROM turns WHERE id = $1", halted_turn_id)
    return True


async def expire_pending_rolls(conn, game_id: UUID) -> None:
    """A rollback discards the action a pending roll belongs to: it never comes back (#32)."""
    await conn.execute(
        "UPDATE mechanic_rolls SET status = 'expired' WHERE game_id = $1 AND status = 'pending'",
        game_id,
    )
