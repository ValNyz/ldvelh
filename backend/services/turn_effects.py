"""Turn effects: what a narration changes in the world, applied in the commit transaction.

Cycle, date, time and location, stub events, credit delta, entity reveals and compel.
No function opens its own connection or transaction: the commit step runs them all in
one transaction, so a failure anywhere leaves nothing behind (#20). The SQL of the turn's
own rows (messages, rolls, turns) is in repos/turns.py.
"""

import logging
from uuid import UUID

from config import get_settings
from domain.turn import AppliedCredit, AppliedDeltas, NarrationState
from kg import refs
from kg.item_writes import write_item
from kg.populator import KnowledgeGraphPopulator
from kg.reader import KnowledgeGraphReader
from schema import DEFAULT_GAME_TIME
from schema.narration import NarrationOutput
from services.identity.reveals import apply_entity_reveals
from services.identity.service import IdentityService
from domain.identity import NewEntitySpec
from utils.log_safe import log_cause

logger = logging.getLogger(__name__)


def _populator(game_id: UUID) -> KnowledgeGraphPopulator:
    # Built without a pool: the methods used here only take `conn`.
    return KnowledgeGraphPopulator(None, game_id)


async def _resolve_location(
    conn, populator: KnowledgeGraphPopulator, location: str, new_cycle: int
) -> UUID | None:
    """Id of the narrated location (C10): the live location its name or handle resolves
    to, else a stub created through the identity service (enriched by the extraction).
    A removed location of that name is never the turn's place: a fresh one is created
    (internal label suffix, the player reads the bare name). A name two live locations
    share never creates a duplicate: None."""
    identity = await populator.identity(conn)
    resolved, candidates = await identity.resolve_live_ref(conn, location, "location")
    if resolved is not None:
        location_id = resolved.entity_id
    else:
        if candidates > 1:
            return None
        location_id = await write_item(
            conn,
            # No list kept: an IdentityFailure is an identity_events row, logged without
            # story text; the commit goes on without a location.
            [],
            "narrated location",
            lambda: identity.create_entity(
                conn,
                NewEntitySpec(
                    "location",
                    location,
                    "descriptor",
                    fields={"created_cycle": new_cycle},
                ),
                turn_id=None,
                source="system",
                # No live location has the name: only removed ones may hold it.
                trap=True,
            ),
            "[COMMIT] ",
        )
        if location_id is None:
            return None
    old_id = await conn.fetchval(
        "SELECT current_location_id FROM games WHERE id = $1", populator.game_id
    )
    if old_id != location_id:
        # Ids only: a location name is story text.
        logger.info(f"[GAME] Location changed: {old_id} → {location_id}")
    return location_id


async def apply_narration_state(
    conn, game_id: UUID, narration: NarrationOutput, current_cycle: int
) -> NarrationState:
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
            logger.warning(
                f"[GAME] day_transition without new_date, using '{new_date}'"
            )

    location_id = None
    if location:
        location_id = await _resolve_location(conn, populator, location, new_cycle)

    for evt in narration.events_mentioned:
        await populator.create_stub_event(
            conn,
            evt,
            new_cycle,
            await _place(conn, populator, "stub event location", evt.location),
        )

    await populator.update_game_state(
        conn,
        cycle=new_cycle,
        date=new_date,
        time=new_time,
        location_id=location_id,
    )

    return NarrationState(
        cycle=new_cycle,
        time=new_time,
        location=location,
        npcs_present=narration.npcs_present or [],
        date=new_date,
        location_id=location_id,
        location_resolved=True,
    )


async def _place(conn, populator, label: str, location: str | None) -> UUID | None:
    """A live location the commit writes as a place (a stub event's, C12, or a message's
    when its state carries none): an unresolved or removed one is counted (`ref_dropped`,
    identity_events) and the row is written without it."""
    return await refs.optional(
        await populator.identity(conn), conn, [], label, location, "location", live=True
    )


async def _apply_compel(conn, game_id: UUID, narration: NarrationOutput) -> dict | None:
    """Fate Core compel: +1 fate point if accepted, -1 (floor 0) if refused."""
    if narration.compel_result not in ("accepted", "refused"):
        return None
    try:
        # Savepoint: a failed statement must not abort the turn's transaction.
        async with conn.transaction():
            fp = await conn.fetchval(
                "SELECT fate_points FROM character_fate WHERE game_id = $1", game_id
            )
            if fp is None:
                return None
            accepted = narration.compel_result == "accepted"
            new_fp = fp + 1 if accepted else max(0, fp - 1)
            await conn.execute(
                "UPDATE character_fate SET fate_points = $1 WHERE game_id = $2",
                new_fp,
                game_id,
            )
    except Exception as e:  # noqa: BLE001 - a failed compel never aborts the commit
        log_cause(
            logger,
            logging.WARNING,
            "[COMPEL] FP adjustment failed",
            e,
            debug_detail=get_settings().log_prompts,
        )
        return None
    return {
        "result": narration.compel_result,
        "aspect": narration.compel_aspect,
        "fp_change": 1 if accepted else -1,
        "new_fp": new_fp,
    }


async def apply_narrator_deltas(
    conn, game_id: UUID, narration: NarrationOutput, cycle: int
) -> AppliedDeltas:
    """Credit delta, entity reveals and compel, applied on the spot."""
    populator = _populator(game_id)
    credit = None
    if narration.credit_delta:
        cd = narration.credit_delta
        applied, new_balance, error = await populator.credit_transaction(
            conn, cd.amount, cycle, cd.description
        )
        credit = AppliedCredit(
            amount=cd.amount,
            description=cd.description,
            applied=applied,
            new_balance=new_balance,
            error=error,
        )

    if narration.entity_reveals:
        await apply_entity_reveals(
            conn,
            await IdentityService.for_game(conn, game_id),
            narration.entity_reveals,
            turn_id=None,
            source="reveal",
            log_prefix="[COMMIT] ",
        )

    return AppliedDeltas(
        credit=credit, compel=await _apply_compel(conn, game_id, narration)
    )
