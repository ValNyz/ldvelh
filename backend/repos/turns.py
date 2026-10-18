"""Turn repository: every write of a narration turn, on the caller's connection.

No function opens its own connection or transaction: the commit step runs them all
in one transaction, so a failure anywhere leaves nothing behind (#20).
"""

import logging
from uuid import UUID

from domain.turn import AppliedCredit, AppliedDeltas, NarrationState
from kg.populator import KnowledgeGraphPopulator
from kg.reader import KnowledgeGraphReader
from schema.core import DEFAULT_GAME_TIME
from schema.engine import RollResult
from schema.narration import NarrationOutput
from config import get_settings
from utils.json_utils import parse_json
from utils.log_safe import log_cause

logger = logging.getLogger(__name__)


def _populator(game_id: UUID) -> KnowledgeGraphPopulator:
    # Built without a pool: the methods used here only take `conn`.
    return KnowledgeGraphPopulator(None, game_id)


async def _resolve_location(conn, game_id: UUID, location: str, new_cycle: int) -> UUID | None:
    """Id of the narrated location, created as a stub when unknown."""
    location_id = await conn.fetchval(
        "SELECT id FROM locations WHERE game_id = $1 AND LOWER(name) = LOWER($2)",
        game_id, location,
    )
    if location_id:
        old_loc = await KnowledgeGraphReader(None, game_id).get_current_location_name(conn)
        if old_loc and old_loc.lower() != location.lower():
            logger.info(f"[GAME] Location changed: '{old_loc}' → '{location}'")
        return location_id
    # Create a stub location (will be fully populated during extraction)
    location_id = await conn.fetchval(
        """INSERT INTO locations (game_id, name, created_cycle)
        VALUES ($1, $2, $3)
        ON CONFLICT (game_id, name) DO NOTHING
        RETURNING id""",
        game_id, location, new_cycle,
    )
    if not location_id:
        # Race condition: created between check and insert
        location_id = await conn.fetchval(
            "SELECT id FROM locations WHERE game_id = $1 AND LOWER(name) = LOWER($2)",
            game_id, location,
        )
    logger.info(
        f"[GAME] Created stub location '{location}' "
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
                             engine_snapshot: dict | None) -> tuple[UUID, UUID]:
    """User + assistant message pair of the turn; returns (user_id, assistant_id)."""
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
        conn, conv_id, "user", user_message, sequence=max_seq + 1, **stamp,
    )
    assistant_id = await populator.save_message(
        conn, conv_id, "assistant", assistant_message, sequence=max_seq + 2, **stamp,
        narrator_deltas=narrator_deltas, engine_snapshot=engine_snapshot,
    )
    return user_id, assistant_id


async def lock_engine(conn, game_id: UUID) -> None:
    """The engine is immutable once the first narration turn is saved."""
    await _populator(game_id).lock_engine(conn)


async def log_mechanic_roll(conn, game_id: UUID, *, message_id: UUID, engine: str,
                            roll: RollResult, cycle: int | None) -> UUID:
    """Log a resolved roll with the assistant message that narrated it."""
    return await _populator(game_id).log_mechanic_roll(
        conn, game_id, message_id, engine, roll.details.get("skill_name"),
        roll.model_dump(), roll.outcome, roll.complication, cycle,
    )


async def store_pending_roll(conn, game_id: UUID, roll: RollResult, player_message: str,
                             cycle: int) -> UUID:
    """A failed Fate roll waiting for an aspect invocation (at most one per game)."""
    # Only Fate Core pauses a roll for an invocation.
    return await conn.fetchval(
        """INSERT INTO mechanic_rolls
           (game_id, message_id, engine, skill_used, roll_details, outcome, complication,
            cycle, status, player_message)
           VALUES ($1, NULL, 'fate_core', $2, $3, $4, $5, $6, 'pending', $7)
           RETURNING id""",
        game_id, roll.details.get("skill_name"), roll.model_dump(), roll.outcome,
        roll.complication, cycle, player_message,
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
                             outcome: str, message_id: UUID, cycle: int) -> bool:
    """Resolve the pending roll with its final details; False if it was no longer pending.

    The roll is stored pending at the cycle before its turn (the narration, hence a possible
    day change, does not exist yet): resolving re-stamps it with the turn's post-turn cycle,
    like the turn's messages, so rolling the turn back removes it (#134)."""
    claimed = await conn.fetchval(
        """UPDATE mechanic_rolls
        SET status = 'resolved', roll_details = $3, outcome = $4, message_id = $5, cycle = $6
        WHERE id = $1 AND game_id = $2 AND status = 'pending'
        RETURNING id""",
        roll_id, game_id, roll_details, outcome, message_id, cycle,
    )
    return claimed is not None


async def expire_pending_rolls(conn, game_id: UUID) -> None:
    """A rollback discards the action a pending roll belongs to: it never comes back (#32)."""
    await conn.execute(
        "UPDATE mechanic_rolls SET status = 'expired' WHERE game_id = $1 AND status = 'pending'",
        game_id,
    )
