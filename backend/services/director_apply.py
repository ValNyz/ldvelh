"""
LDVELH - Director plan apply
Stores a Director plan and its arc updates in one transaction (apply step of the run, #96).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from uuid import UUID

from domain.errors import SourceMessageGone
from kg.item_writes import write_item
from repos.uow import uow
from schema.director import DirectorOutput

if TYPE_CHECKING:
    from asyncpg import Connection

logger = logging.getLogger(__name__)


async def apply_director_plan(
    conn: Connection, game_id: UUID, plan: DirectorOutput, *,
    cycle: int, ig_time: str, source_message_id: UUID | None, turn_id: UUID | None,
) -> bool:
    """Store the plan, last_director_time and arc updates in the turn's unit of work.

    The writes are journaled under `turn_id` when given (#105); the initial Director has none.
    With `source_message_id`, the message is share-locked first (a rollback deleting it
    waits for the commit); if it is gone, nothing is written and False is returned.
    Each arc update runs in its own savepoint: a failed one is recorded and logged alone.
    """
    try:
        async with uow(conn, turn_id, source_message_id=source_message_id):
            await _insert_plan(conn, game_id, plan, cycle, ig_time)
            await _update_last_director_time(conn, game_id, ig_time)
            errors: list[str] = []
            for arc_update in plan.arc_updates:
                await write_item(
                    conn, errors, "arc",
                    lambda arc_update=arc_update: _apply_arc_update(
                        conn, game_id, arc_update, cycle),
                    "[DIRECTOR] ",
                )
    except SourceMessageGone:
        logger.warning(f"[DIRECTOR] Source message gone, plan dropped game={game_id}")
        return False
    return True


async def _insert_plan(conn, game_id, plan, cycle, ig_time):
    await conn.execute(
        """INSERT INTO director_plans
           (game_id, cycle, ig_time, tension_level, narrator_guidance, planned_events, long_term_vision)
           VALUES ($1, $2, $3, $4, $5, $6, $7)""",
        game_id,
        cycle,
        ig_time,
        plan.tension_level,
        plan.narrator_guidance,
        [e.model_dump() for e in plan.planned_events],
        plan.long_term_vision,
    )


async def _update_last_director_time(conn, game_id, ig_time):
    await conn.execute(
        "UPDATE games SET last_director_time = $2 WHERE id = $1",
        game_id, ig_time,
    )


async def _apply_arc_update(conn, game_id, arc_update, cycle):
    """Apply a single arc update from the Director."""
    action = arc_update.action.lower()
    title = arc_update.title

    if action == "create":
        existing = await conn.fetchval(
            """SELECT id FROM narrative_arcs
               WHERE game_id = $1 AND LOWER(title) = LOWER($2) AND resolved = false""",
            game_id, title,
        )
        if existing:
            # Same open arc proposed again: update it instead of duplicating it
            await conn.execute(
                """UPDATE narrative_arcs
                   SET description = COALESCE(NULLIF($2, ''), description),
                       intensity = COALESCE($3, intensity), updated_at = now()
                   WHERE id = $1""",
                existing, arc_update.description or "", arc_update.intensity,
            )
            logger.info(f"[DIRECTOR] Arc already open, updated: '{title}'")
            return
        # Create new arc
        arc_id = await conn.fetchval(
            """INSERT INTO narrative_arcs
                   (game_id, title, description, domain, intensity, created_cycle)
               VALUES ($1, $2, $3, $4, $5, $6) RETURNING id""",
            game_id, title,
            arc_update.description or "",
            arc_update.domain or "personal",
            arc_update.intensity or 3,
            cycle,  # the cycle the Director ran for: rollback deletes by it (#85)
        )
        # Link involved entities via arc_participants
        if arc_id and arc_update.involved_entities:
            for entity_name in arc_update.involved_entities:
                entity_id = await conn.fetchval(
                    "SELECT find_entity($1, $2)",  # maps PROTAGONIST_REF too (#28)
                    game_id, entity_name,
                )
                if entity_id:
                    await conn.execute(
                        "INSERT INTO arc_participants (arc_id, entity_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                        arc_id, entity_id,
                    )
        logger.info(f"[DIRECTOR] Arc created: '{title}'")

    elif action == "update":
        # Update existing arc
        updates = []
        params = [game_id, title]
        idx = 3
        if arc_update.description:
            updates.append(f"description = ${idx}")
            params.append(arc_update.description)
            idx += 1
        if arc_update.intensity:
            updates.append(f"intensity = ${idx}")
            params.append(arc_update.intensity)
            idx += 1
        if updates:
            updates.append("updated_at = now()")
            sql = f"UPDATE narrative_arcs SET {', '.join(updates)} WHERE game_id = $1 AND LOWER(title) = LOWER($2) AND resolved = false"
            await conn.execute(sql, *params)
            logger.info(f"[DIRECTOR] Arc updated: '{title}'")

    elif action == "resolve":
        await conn.execute(
            """UPDATE narrative_arcs
               SET resolved = true, resolved_cycle = $3, resolution = $4, updated_at = now()
               WHERE game_id = $1 AND LOWER(title) = LOWER($2) AND resolved = false""",
            game_id, title, cycle, arc_update.resolution or "",
        )
        logger.info(f"[DIRECTOR] Arc resolved: '{title}'")
