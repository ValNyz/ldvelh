"""
LDVELH - Knowledge Graph Reader (Dedicated Tables Architecture)
Read-only operations (SELECT) for all game data.
Uses dedicated tables and views instead of EAV joins.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Literal
from uuid import UUID

if TYPE_CHECKING:
    from asyncpg import Connection, Pool

logger = logging.getLogger(__name__)

SortOrder = Literal["asc", "desc"]


class KnowledgeGraphReader:
    """Read-only access to game data — SELECT only."""

    def __init__(self, pool: Pool, game_id: UUID | None = None):
        self.pool = pool
        self.game_id = game_id

    # =========================================================================
    # GAMES
    # =========================================================================

    async def list_games(
        self, conn: Connection, active_only: bool = True, user_id=None
    ) -> list[dict]:
        """List games with current state, optionally filtered by user."""
        conditions = []
        params = []
        if active_only:
            conditions.append("active = true")
        if user_id is not None:
            params.append(user_id)
            conditions.append(f"user_id = ${len(params)}")

        query = """
            SELECT id, name, active, created_at, updated_at,
                   current_cycle, "current_date", engine
            FROM games
        """
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY updated_at DESC"
        rows = await conn.fetch(query, *params)
        return [dict(r) for r in rows]

    async def get_game(
        self, conn: Connection, game_id: UUID | None = None
    ) -> dict | None:
        target_id = game_id or self.game_id
        row = await conn.fetchrow(
            """SELECT id, name, active, created_at, updated_at,
                      current_cycle, "current_date", "current_time",
                      current_location_id,
                      world_name, world_description, world_atmosphere,
                      world_seed_words, world_founding_cycle,
                      detail_requests,
                      engine, engine_locked, world_config
               FROM games WHERE id = $1""",
            target_id,
        )
        return dict(row) if row else None

    async def game_exists(
        self, conn: Connection, active_only: bool = True
    ) -> bool:
        if active_only:
            return await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM games WHERE id = $1 AND active = true)",
                self.game_id,
            )
        return await conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM games WHERE id = $1)", self.game_id
        )

    # =========================================================================
    # WORLD STATE
    # =========================================================================

    async def is_world_created(self, conn: Connection) -> bool:
        """Check if world is created (protagonist exists)."""
        return await conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM protagonists WHERE game_id = $1)",
            self.game_id,
        )

    async def get_current_cycle(self, conn: Connection) -> int:
        result = await conn.fetchval(
            "SELECT COALESCE(current_cycle, 0) FROM games WHERE id = $1",
            self.game_id,
        )
        return result or 0

    async def get_current_date(self, conn: Connection) -> str | None:
        return await conn.fetchval(
            'SELECT "current_date" FROM games WHERE id = $1', self.game_id
        )

    async def get_current_time(self, conn: Connection) -> str | None:
        return await conn.fetchval(
            'SELECT "current_time" FROM games WHERE id = $1', self.game_id
        )

    async def get_current_location_name(self, conn: Connection) -> str | None:
        return await conn.fetchval(
            """SELECT l.name FROM games g
               JOIN locations l ON g.current_location_id = l.id
               WHERE g.id = $1""",
            self.game_id,
        )

    # =========================================================================
    # ENTITY REGISTRY
    # =========================================================================

    async def get_entities(
        self, conn: Connection, entity_type: str | None = None
    ) -> list[dict]:
        """Get all entities from entity_registry."""
        query = "SELECT id, entity_type, name FROM entity_registry WHERE game_id = $1"
        params: list = [self.game_id]
        if entity_type:
            query += " AND entity_type = $2"
            params.append(entity_type)
        rows = await conn.fetch(query, *params)
        return [dict(r) for r in rows]

    async def resolve_entity_refs(
        self, conn: Connection, names: list[str]
    ) -> dict[str, UUID]:
        """Resolve multiple names to {name_lower: entity_registry UUID}."""
        if not names:
            return {}
        rows = await conn.fetch(
            """SELECT LOWER(name) as name_lower, id FROM entity_registry
               WHERE game_id = $1 AND LOWER(name) = ANY($2)""",
            self.game_id,
            [n.lower() for n in names],
        )
        return {r["name_lower"]: r["id"] for r in rows}

    async def get_entity_counts_by_type(self, conn: Connection) -> dict[str, int]:
        """Count active entities per type."""
        row = await conn.fetchrow(
            """SELECT
                (SELECT COUNT(*) FROM characters WHERE game_id=$1 AND removed_cycle IS NULL) as characters,
                (SELECT COUNT(*) FROM locations WHERE game_id=$1 AND removed_cycle IS NULL) as locations,
                (SELECT COUNT(*) FROM organizations WHERE game_id=$1 AND removed_cycle IS NULL) as organizations,
                (SELECT COUNT(*) FROM objects WHERE game_id=$1 AND removed_cycle IS NULL) as objects
            """,
            self.game_id,
        )
        return dict(row) if row else {}

    # =========================================================================
    # PROTAGONIST
    # =========================================================================

    async def get_protagonist(self, conn: Connection) -> dict | None:
        """Get protagonist with all fields."""
        row = await conn.fetchrow(
            """SELECT p.id, p.name,
                      p.credits,
                      p.occupation, p.origin, p.departure_reason,
                      p.backstory, p.hobbies, p.description,
                      p.employer_id, p.residence_id, p.details,
                      o.name as employer_name,
                      l.name as residence_name
               FROM protagonists p
               LEFT JOIN organizations o ON p.employer_id = o.id
               LEFT JOIN locations l ON p.residence_id = l.id
               WHERE p.game_id = $1""",
            self.game_id,
        )
        if not row:
            return None
        result = dict(row)

        # Add skills
        skills = await conn.fetch(
            "SELECT name, level FROM skills"
            " WHERE protagonist_id = $1 AND end_cycle IS NULL",
            result["id"],
        )
        result["skills"] = [dict(s) for s in skills]
        return result

    async def get_protagonist_stats(self, conn: Connection) -> dict | None:
        """Get protagonist credits only."""
        row = await conn.fetchrow(
            "SELECT credits FROM protagonists WHERE game_id = $1",
            self.game_id,
        )
        return dict(row) if row else None

    # =========================================================================
    # PERSONAL ASSISTANT
    # =========================================================================

    async def get_personal_assistant(self, conn: Connection) -> dict | None:
        row = await conn.fetchrow(
            "SELECT id, name, voice, traits, quirk, substrate, details"
            " FROM personal_assistants WHERE game_id = $1",
            self.game_id,
        )
        return dict(row) if row else None

    # =========================================================================
    # CHARACTERS
    # =========================================================================

    async def get_all_characters(self, conn: Connection) -> list[dict]:
        """Get all active NPCs with their fields and relation to protagonist."""
        rows = await conn.fetch(
            """SELECT
                c.id, c.name, c.known_by_protagonist, c.unknown_name,
                c.species, c.gender, c.pronouns, c.age, c.description,
                c.traits, c.mood, c.occupation, c.origin,
                c.romantic_potential, c.is_mandatory, c.ambient,
                wp.name as workplace_name,
                res.name as residence_name,
                -- Relation to protagonist
                r_knows.level as relation_level,
                r_knows.context as relation_context,
                -- Usual location (first spatial relation target)
                (SELECT l.name FROM relations r_sp
                 JOIN entity_registry er_src ON r_sp.source_id = er_src.id AND er_src.name = c.name
                 JOIN entity_registry er_tgt ON r_sp.target_id = er_tgt.id
                 JOIN locations l ON l.game_id = c.game_id AND l.name = er_tgt.name
                 WHERE r_sp.game_id = c.game_id
                   AND r_sp.type IN ('works_at', 'lives_at', 'frequents')
                   AND r_sp.end_cycle IS NULL
                 LIMIT 1) as usual_location
            FROM characters c
            LEFT JOIN locations wp ON c.workplace_id = wp.id
            LEFT JOIN locations res ON c.residence_id = res.id
            -- Join protagonist relation via entity_registry
            LEFT JOIN LATERAL (
                SELECT r.level, r.context
                FROM relations r
                JOIN entity_registry er_proto ON r.source_id = er_proto.id
                    AND er_proto.entity_type = 'protagonist'
                JOIN entity_registry er_char ON r.target_id = er_char.id
                    AND er_char.name = c.name
                WHERE r.game_id = c.game_id
                  AND r.type = 'knows'
                  AND r.end_cycle IS NULL
                LIMIT 1
            ) r_knows ON true
            WHERE c.game_id = $1 AND c.removed_cycle IS NULL
            ORDER BY COALESCE(r_knows.level, 0) DESC, c.name ASC""",
            self.game_id,
        )
        return [dict(r) for r in rows]

    async def get_known_characters(self, conn: Connection) -> list[dict]:
        """Get NPCs known by the protagonist."""
        all_chars = await self.get_all_characters(conn)
        return [c for c in all_chars if c["known_by_protagonist"]]

    async def get_npcs_at_location(
        self, conn: Connection, location_name: str
    ) -> list[dict]:
        """Get NPCs whose spatial relations point to a given location."""
        rows = await conn.fetch(
            """SELECT DISTINCT
                c.id, c.name, c.known_by_protagonist, c.unknown_name,
                c.species, c.occupation, c.traits, c.mood, c.ambient,
                r_knows.level as relation_level,
                r_knows.context as relation_context
            FROM characters c
            JOIN entity_registry er_c ON er_c.game_id = c.game_id
                AND er_c.entity_type = 'character' AND er_c.name = c.name
            JOIN relations r ON r.source_id = er_c.id
                AND r.type IN ('works_at', 'frequents', 'lives_at')
                AND r.end_cycle IS NULL
            JOIN entity_registry er_loc ON r.target_id = er_loc.id
                AND LOWER(er_loc.name) = LOWER($2)
            -- Protagonist relation
            LEFT JOIN LATERAL (
                SELECT rel.level, rel.context
                FROM relations rel
                JOIN entity_registry er_p ON rel.source_id = er_p.id
                    AND er_p.entity_type = 'protagonist'
                WHERE rel.target_id = er_c.id
                  AND rel.type = 'knows' AND rel.end_cycle IS NULL
                LIMIT 1
            ) r_knows ON true
            WHERE c.game_id = $1 AND c.removed_cycle IS NULL""",
            self.game_id,
            location_name,
        )
        return [dict(r) for r in rows]

    # =========================================================================
    # LOCATIONS
    # =========================================================================

    async def get_locations(self, conn: Connection) -> list[dict]:
        """Get all active locations."""
        rows = await conn.fetch(
            """SELECT l.id, l.name, l.location_type, l.sector,
                      l.description, l.atmosphere, l.accessible,
                      l.notable_features, l.ambient,
                      p.name as parent_location_name
               FROM locations l
               LEFT JOIN locations p ON l.parent_id = p.id
               WHERE l.game_id = $1 AND l.removed_cycle IS NULL
               ORDER BY l.sector NULLS LAST, l.name ASC""",
            self.game_id,
        )
        return [dict(r) for r in rows]

    async def get_location_by_name(
        self, conn: Connection, name: str
    ) -> dict | None:
        row = await conn.fetchrow(
            """SELECT l.id, l.name, l.location_type, l.sector,
                      l.description, l.atmosphere, l.accessible,
                      l.notable_features, l.typical_crowd,
                      l.operating_hours, l.price_range, l.ambient,
                      p.name as parent_location_name
               FROM locations l
               LEFT JOIN locations p ON l.parent_id = p.id
               WHERE l.game_id = $1 AND LOWER(l.name) = LOWER($2)
                 AND l.removed_cycle IS NULL""",
            self.game_id,
            name,
        )
        return dict(row) if row else None

    async def get_root_location(self, conn: Connection) -> dict | None:
        """Get the top-level location (station)."""
        row = await conn.fetchrow(
            """SELECT id, name, location_type, atmosphere,
                      description, notable_features
               FROM locations
               WHERE game_id = $1 AND parent_id IS NULL
                 AND removed_cycle IS NULL
               ORDER BY created_at ASC LIMIT 1""",
            self.game_id,
        )
        return dict(row) if row else None

    async def get_sibling_locations(
        self, conn: Connection, location_name: str, limit: int = 10
    ) -> list[dict]:
        """Get accessible locations in the same sector or nearby."""
        rows = await conn.fetch(
            """WITH current AS (
                SELECT id, sector FROM locations
                WHERE game_id = $1 AND LOWER(name) = LOWER($2)
                  AND removed_cycle IS NULL
                LIMIT 1
            )
            SELECT l.name, l.location_type, l.sector, l.atmosphere, l.ambient
            FROM locations l, current c
            WHERE l.game_id = $1
              AND l.removed_cycle IS NULL
              AND l.id != c.id
              AND l.parent_id IS NOT NULL
              AND (l.accessible = true OR l.sector = c.sector)
            LIMIT $3""",
            self.game_id,
            location_name,
            limit,
        )
        return [dict(r) for r in rows]

    # =========================================================================
    # ORGANIZATIONS
    # =========================================================================

    async def get_organizations(self, conn: Connection) -> list[dict]:
        """Get all active organizations."""
        rows = await conn.fetch(
            """SELECT o.id, o.name, o.org_type, o.domain, o.size,
                      o.description, o.reputation, o.ambient,
                      l.name as headquarters_name
               FROM organizations o
               LEFT JOIN locations l ON o.headquarters_id = l.id
               WHERE o.game_id = $1 AND o.removed_cycle IS NULL
               ORDER BY o.name ASC""",
            self.game_id,
        )
        return [dict(r) for r in rows]

    async def get_stub_locations(self, conn: Connection) -> list[str]:
        """Get location names that are stubs (name only, no description)."""
        rows = await conn.fetch(
            "SELECT name FROM locations WHERE game_id=$1"
            " AND description IS NULL AND removed_cycle IS NULL",
            self.game_id,
        )
        return [r["name"] for r in rows]

    # =========================================================================
    # INVENTORY (via view v_protagonist_inventory)
    # =========================================================================

    async def get_inventory(self, conn: Connection) -> list[dict]:
        """Get protagonist's inventory."""
        rows = await conn.fetch(
            "SELECT * FROM v_protagonist_inventory WHERE game_id = $1",
            self.game_id,
        )
        return [dict(r) for r in rows]

    # =========================================================================
    # RELATIONS (via view v_active_relations)
    # =========================================================================

    async def get_relations(
        self,
        conn: Connection,
        entity_name: str | None = None,
        relation_type: str | None = None,
    ) -> list[dict]:
        """Get active relations, optionally filtered."""
        query = """
            SELECT relation_id, relation_type,
                   source_name, source_type,
                   target_name, target_type,
                   level, context, known_by_protagonist, start_cycle
            FROM v_active_relations
            WHERE game_id = $1
        """
        params: list = [self.game_id]

        if entity_name:
            params.append(entity_name.lower())
            query += (
                f" AND (LOWER(source_name) = ${len(params)}"
                f" OR LOWER(target_name) = ${len(params)})"
            )

        if relation_type:
            params.append(relation_type)
            query += f" AND relation_type = ${len(params)}::relation_type"

        rows = await conn.fetch(query, *params)
        return [dict(r) for r in rows]

    async def get_protagonist_relation_to(
        self, conn: Connection, npc_name: str
    ) -> dict | None:
        """Get the protagonist's 'knows' relation to an NPC."""
        row = await conn.fetchrow(
            """SELECT level, context, known_by_protagonist
               FROM v_active_relations
               WHERE game_id = $1
                 AND source_type = 'protagonist'
                 AND LOWER(target_name) = LOWER($2)
                 AND relation_type = 'knows'""",
            self.game_id,
            npc_name,
        )
        return dict(row) if row else None

    # =========================================================================
    # FACTS (via view v_recent_facts)
    # =========================================================================

    async def get_facts(
        self,
        conn: Connection,
        cycle: int | None = None,
        min_importance: int = 1,
        limit: int = 20,
        order: SortOrder = "desc",
    ) -> list[dict]:
        """Get facts with optional filters."""
        query = """
            SELECT id, cycle, time, type, description,
                   importance, semantic_key, location_name, participants
            FROM v_recent_facts
            WHERE game_id = $1 AND importance >= $2
        """
        params: list = [self.game_id, min_importance]

        if cycle is not None:
            params.append(cycle)
            query += f" AND cycle <= ${len(params)}"

        query += f" ORDER BY importance DESC, cycle {order.upper()}"
        params.append(limit)
        query += f" LIMIT ${len(params)}"

        rows = await conn.fetch(query, *params)
        return [dict(r) for r in rows]

    async def fact_exists(
        self, conn: Connection, cycle: int, semantic_key: str
    ) -> bool:
        return await conn.fetchval(
            """SELECT EXISTS(
                SELECT 1 FROM facts
                WHERE game_id = $1 AND cycle = $2 AND semantic_key = $3
            )""",
            self.game_id,
            cycle,
            semantic_key,
        )

    # =========================================================================
    # NARRATIVE ARCS (via view v_active_arcs)
    # =========================================================================

    async def get_active_arcs(self, conn: Connection) -> list[dict]:
        """Get active narrative arcs with participants and owner info."""
        rows = await conn.fetch(
            """SELECT v.id, v.title, v.domain, v.description,
                      v.intensity, v.progress, v.situation, v.desire, v.obstacle,
                      v.stakes, v.deadline_cycle, v.participants,
                      na.owner_id, na.objective, na.steps,
                      er.name as owner_name, er.entity_type as owner_type
               FROM v_active_arcs v
               JOIN narrative_arcs na ON na.id = v.id
               LEFT JOIN entity_registry er ON na.owner_id = er.id
               WHERE v.game_id = $1
               ORDER BY v.intensity DESC, v.deadline_cycle ASC NULLS LAST""",
            self.game_id,
        )
        return [dict(r) for r in rows]

    async def find_arc_by_title(
        self, conn: Connection, title: str
    ) -> dict | None:
        """Find an arc by partial title match."""
        row = await conn.fetchrow(
            """SELECT id, title, domain, description, resolved
               FROM narrative_arcs
               WHERE game_id = $1 AND resolved = false
                 AND title ILIKE '%' || $2 || '%'
               LIMIT 1""",
            self.game_id,
            title[:50],
        )
        return dict(row) if row else None

    # =========================================================================
    # EVENTS (via view v_upcoming_events)
    # =========================================================================

    async def get_upcoming_events(
        self, conn: Connection, from_cycle: int, limit: int = 5
    ) -> list[dict]:
        """Get upcoming events with participants."""
        rows = await conn.fetch(
            """SELECT id, type, title, description,
                      planned_cycle, time, location_name, participants
               FROM v_upcoming_events
               WHERE game_id = $1 AND planned_cycle >= $2
               ORDER BY planned_cycle ASC
               LIMIT $3""",
            self.game_id,
            from_cycle,
            limit,
        )
        return [dict(r) for r in rows]

    async def get_events(
        self,
        conn: Connection,
        from_cycle: int | None = None,
        limit: int | None = None,
        pending_only: bool = True,
    ) -> list[dict]:
        """Get events with basic filters."""
        query = """
            SELECT id, title, description, planned_cycle,
                   time, location_id, type, completed, cancelled
            FROM events WHERE game_id = $1
        """
        params: list = [self.game_id]

        if pending_only:
            query += " AND completed = false AND cancelled = false"

        if from_cycle is not None:
            params.append(from_cycle)
            query += f" AND planned_cycle >= ${len(params)}"

        query += " ORDER BY planned_cycle ASC"

        if limit:
            params.append(limit)
            query += f" LIMIT ${len(params)}"

        rows = await conn.fetch(query, *params)
        return [dict(r) for r in rows]

    # =========================================================================
    # MESSAGES & CONVERSATIONS
    # =========================================================================

    async def get_conversations(
        self, conn: Connection, active_only: bool = True
    ) -> list[dict]:
        """Get conversation segments."""
        query = """
            SELECT id, start_cycle, end_cycle, compacted, created_at
            FROM conversations WHERE game_id = $1
        """
        if active_only:
            query += " AND compacted = false"
        query += " ORDER BY created_at DESC"
        rows = await conn.fetch(query, self.game_id)
        return [dict(r) for r in rows]

    async def get_messages(
        self,
        conn: Connection,
        conversation_id: UUID | None = None,
        limit: int | None = None,
        order: SortOrder = "asc",
    ) -> list[dict]:
        """Get messages, optionally scoped to a conversation."""
        query = """
            SELECT m.id, m.role, m.content, m.cycle, m.game_date, m.time,
                   m.location_id, m.sequence, m.created_at,
                   m.narrator_deltas,
                   l.name as location_name,
                   mr.roll_details
            FROM messages m
            LEFT JOIN locations l ON m.location_id = l.id
            LEFT JOIN mechanic_rolls mr ON mr.message_id = m.id
            WHERE m.game_id = $1
        """
        params: list = [self.game_id]

        if conversation_id:
            params.append(conversation_id)
            query += f" AND m.conversation_id = ${len(params)}"

        query += f" ORDER BY m.sequence {order.upper()}"

        if limit:
            params.append(limit)
            query += f" LIMIT ${len(params)}"

        rows = await conn.fetch(query, *params)
        return [dict(r) for r in rows]

    async def get_last_assistant_message(
        self, conn: Connection
    ) -> dict | None:
        """Get the most recent assistant message with location name."""
        row = await conn.fetchrow(
            """SELECT m.id, m.cycle, m.time, m.location_id, m.sequence,
                      l.name as location_name
               FROM messages m
               LEFT JOIN locations l ON m.location_id = l.id
               WHERE m.game_id = $1 AND m.role = 'assistant'
               ORDER BY m.sequence DESC LIMIT 1""",
            self.game_id,
        )
        return dict(row) if row else None

    async def get_message_count(self, conn: Connection) -> int:
        return await conn.fetchval(
            "SELECT COUNT(*) FROM messages WHERE game_id = $1", self.game_id
        )

    # =========================================================================
    # NARRATIVE SEEDS
    # =========================================================================

    async def get_active_seeds(
        self, conn: Connection, limit: int = 15
    ) -> list[dict]:
        """Get active narrative seeds, most recent first."""
        rows = await conn.fetch(
            """SELECT s.id, s.cycle, s.text, s.created_at,
                      l.name as location_name
               FROM narrative_seeds s
               LEFT JOIN locations l ON s.location_id = l.id
               WHERE s.game_id = $1 AND s.status = 'active'
               ORDER BY s.cycle DESC
               LIMIT $2""",
            self.game_id, limit,
        )
        return [dict(r) for r in rows]

    # =========================================================================
    # CHRONOLOGY (via view v_chronology)
    # =========================================================================

    async def get_chronology(
        self,
        conn: Connection,
        max_cycle: int | None = None,
        limit: int = 7,
        order: SortOrder = "desc",
    ) -> list[dict]:
        """Get chronology entries with NPC participants."""
        query = """
            SELECT id, cycle, time, location_name, summary, npcs_present
            FROM v_chronology
            WHERE game_id = $1
        """
        params: list = [self.game_id]

        if max_cycle is not None:
            params.append(max_cycle)
            query += f" AND cycle <= ${len(params)}"

        query += f" ORDER BY cycle {order.upper()}"
        params.append(limit)
        query += f" LIMIT ${len(params)}"

        rows = await conn.fetch(query, *params)
        return [dict(r) for r in rows]

    async def get_chronology_entry(
        self, conn: Connection, cycle: int
    ) -> dict | None:
        results = await self.get_chronology(conn, max_cycle=cycle, limit=1)
        if results and results[0]["cycle"] == cycle:
            return results[0]
        return None

    # =========================================================================
    # ARRIVAL EVENT (reconstructed from facts + chronology)
    # =========================================================================

    async def get_arrival_event(self, conn: Connection) -> dict | None:
        """Get arrival event data from facts and chronology."""
        # Get chronology entry for cycle 0
        chrono = await conn.fetchrow(
            """SELECT summary, time FROM chronology
               WHERE game_id = $1 AND cycle = 0 LIMIT 1""",
            self.game_id,
        )

        # Get arrival facts
        facts = await conn.fetch(
            """SELECT semantic_key, description FROM facts
               WHERE game_id = $1 AND cycle = 1
                 AND semantic_key LIKE 'valentin:arrival:%'""",
            self.game_id,
        )

        if not chrono and not facts:
            return None

        # Get game state for arrival date
        game = await conn.fetchrow(
            'SELECT "current_date" FROM games WHERE id = $1', self.game_id
        )

        result: dict = {}
        if chrono:
            result["summary"] = chrono["summary"]
            result["time"] = chrono["time"]
        if game:
            result["date"] = game["current_date"]

        for fact in facts:
            key = fact["semantic_key"]
            desc = fact["description"]
            if key == "valentin:arrival:station":
                result["arrival_description"] = desc
            elif key == "valentin:arrival:incident":
                result["incident"] = desc
            elif key == "valentin:arrival:mood" and desc.startswith(
                "État à l'arrivée : "
            ):
                result["initial_mood"] = desc[19:]
            elif key == "valentin:arrival:need" and desc.startswith(
                "Besoin immédiat : "
            ):
                result["immediate_need"] = desc[18:]

        return result

    # =========================================================================
    # OBJECTS
    # =========================================================================

    async def get_object_canonical_names(self, conn: Connection) -> list[str]:
        """Get all canonical_name values for active objects in this game."""
        rows = await conn.fetch(
            "SELECT canonical_name FROM objects"
            " WHERE game_id = $1 AND canonical_name IS NOT NULL"
            " AND removed_cycle IS NULL",
            self.game_id,
        )
        return [r["canonical_name"] for r in rows]

    async def get_objects(self, conn: Connection) -> list[dict]:
        """Get all active objects."""
        rows = await conn.fetch(
            """SELECT id, name, canonical_name, category, description,
                      transportable, stackable, base_value
               FROM objects
               WHERE game_id = $1 AND removed_cycle IS NULL
               ORDER BY name ASC""",
            self.game_id,
        )
        return [dict(r) for r in rows]

    # =========================================================================
    # BATCH EXTRACTION SUPPORT
    # =========================================================================

    async def get_messages_for_cycles(
        self,
        conn: Connection,
        from_cycle: int,
        to_cycle: int,
    ) -> list[dict]:
        """Get all messages within a cycle range, ordered by sequence."""
        rows = await conn.fetch(
            """SELECT m.id, m.role, m.content, m.cycle, m.time,
                      l.name as location_name, m.narrator_deltas
               FROM messages m
               LEFT JOIN locations l ON m.location_id = l.id
               WHERE m.game_id = $1
                 AND m.cycle >= $2
                 AND m.cycle <= $3
               ORDER BY m.sequence ASC""",
            self.game_id, from_cycle, to_cycle,
        )
        return [dict(r) for r in rows]

    async def get_detail_requests(self, conn: Connection) -> list[str]:
        """Get entity detail requests from games table."""
        result = await conn.fetchval(
            "SELECT detail_requests FROM games WHERE id = $1",
            self.game_id,
        )
        return result or []

    async def get_entity_details_by_name(
        self, conn: Connection, name: str
    ) -> dict | None:
        """Load full details of an entity by name (character, location, or org)."""
        # Try character
        row = await conn.fetchrow(
            """SELECT c.*, r.level as relation_level, r.context as relation_context
               FROM characters c
               LEFT JOIN entity_registry er ON er.game_id = c.game_id
                   AND er.entity_type = 'character' AND er.name = c.name
               LEFT JOIN relations r ON r.game_id = c.game_id
                   AND r.target_id = er.id AND r.end_cycle IS NULL
                   AND r.source_id = (
                       SELECT id FROM entity_registry
                       WHERE game_id = $1 AND entity_type = 'protagonist'
                       LIMIT 1
                   )
               WHERE c.game_id = $1 AND LOWER(c.name) = LOWER($2)
                 AND c.removed_cycle IS NULL""",
            self.game_id, name,
        )
        if row:
            d = dict(row)
            d["_entity_type"] = "character"
            # Load recent facts involving this character
            d["recent_facts"] = await self._get_entity_recent_facts(conn, name, limit=5)
            return d

        # Try location
        row = await conn.fetchrow(
            """SELECT * FROM locations
               WHERE game_id = $1 AND LOWER(name) = LOWER($2)
                 AND removed_cycle IS NULL""",
            self.game_id, name,
        )
        if row:
            d = dict(row)
            d["_entity_type"] = "location"
            d["recent_facts"] = await self._get_entity_recent_facts(conn, name, limit=5)
            return d

        # Try organization
        row = await conn.fetchrow(
            """SELECT * FROM organizations
               WHERE game_id = $1 AND LOWER(name) = LOWER($2)
                 AND removed_cycle IS NULL""",
            self.game_id, name,
        )
        if row:
            d = dict(row)
            d["_entity_type"] = "organization"
            d["recent_facts"] = await self._get_entity_recent_facts(conn, name, limit=5)
            return d

        return None

    async def _get_entity_recent_facts(
        self, conn: Connection, entity_name: str, limit: int = 5
    ) -> list[dict]:
        """Get recent facts involving a specific entity."""
        rows = await conn.fetch(
            """SELECT f.cycle, f.type, f.description, f.importance
               FROM facts f
               JOIN fact_participants fp ON fp.fact_id = f.id
               JOIN entity_registry er ON er.id = fp.entity_id
               WHERE f.game_id = $1 AND LOWER(er.name) = LOWER($2)
               ORDER BY f.cycle DESC, f.importance DESC
               LIMIT $3""",
            self.game_id, entity_name, limit,
        )
        return [dict(r) for r in rows]

    # =========================================================================
    # ENGINE
    # =========================================================================

    async def get_engine_type(self, conn: Connection) -> str:
        """Get the engine type for this game."""
        result = await conn.fetchval(
            "SELECT engine FROM games WHERE id = $1", self.game_id
        )
        return result or "none"

    async def get_world_config(self, conn: Connection) -> dict | None:
        """Get the world configuration for this game."""
        return await conn.fetchval(
            "SELECT world_config FROM games WHERE id = $1", self.game_id
        )

    async def is_engine_locked(self, conn: Connection) -> bool:
        """Check if engine is locked (no longer changeable)."""
        result = await conn.fetchval(
            "SELECT engine_locked FROM games WHERE id = $1", self.game_id
        )
        return bool(result)

    async def get_mechanic_rolls(
        self,
        conn: Connection,
        cycle: int | None = None,
        limit: int = 10,
    ) -> list[dict]:
        """Get mechanic roll history."""
        query = """
            SELECT id, engine, skill_used, roll_details, outcome,
                   complication, cycle, created_at
            FROM mechanic_rolls
            WHERE game_id = $1
        """
        params: list = [self.game_id]
        if cycle is not None:
            params.append(cycle)
            query += f" AND cycle = ${len(params)}"
        query += " ORDER BY created_at DESC"
        params.append(limit)
        query += f" LIMIT ${len(params)}"

        rows = await conn.fetch(query, *params)
        return [dict(r) for r in rows]

    async def get_engine_snapshot_for_cycle(
        self, conn: Connection, cycle: int
    ) -> dict | None:
        """Get the engine snapshot from the last assistant message at or before a cycle."""
        result = await conn.fetchval(
            """SELECT engine_snapshot FROM messages
               WHERE game_id = $1 AND role = 'assistant'
                 AND cycle <= $2 AND engine_snapshot IS NOT NULL
               ORDER BY sequence DESC LIMIT 1""",
            self.game_id,
            cycle,
        )
        return result
