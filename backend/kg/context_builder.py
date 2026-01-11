"""
LDVELH - Context Builder (EAV Architecture)
Builds narration context from database using EAV views
"""

from __future__ import annotations
import json
from uuid import UUID
from typing import TYPE_CHECKING

from schema.narration import (
    NarrationContext,
    GaugeState,
    ProtagonistState,
    InventoryItem,
    LocationSummary,
    NPCSummary,
    ArcSummary,
    CommitmentSummary,
    EventSummary,
    RecentFact,
    MessageSummary,
    PersonalAISummary,
)
from schema import ArcDomain

if TYPE_CHECKING:
    from asyncpg import Connection


class ContextBuilder:
    """Builds NarrationContext from database using EAV architecture"""

    def __init__(self, pool, game_id: UUID):
        self.pool = pool
        self.game_id = game_id

    async def build(
        self,
        conn: Connection,
        player_input: str,
        current_cycle: int,
        current_time: str,
        current_location_name: str,
    ) -> NarrationContext:
        """Build complete context for narrator"""

        world_info = await self._get_world_info(conn)
        date = await self._get_date_info(conn, current_cycle)
        protagonist = await self._get_protagonist_state(conn)
        inventory = await self._get_inventory(conn)
        personal_ai = await self._get_personal_ai(conn)
        current_location = await self._get_location(conn, current_location_name)
        connected_locations = await self._get_connected_locations(
            conn, current_location_name
        )
        npcs_present = await self._get_npcs_at_location(
            conn, current_location_name, current_time
        )
        npcs_relevant = await self._get_relevant_npcs(conn, current_cycle)
        commitments = await self._get_active_commitments(conn)
        events = await self._get_upcoming_events(conn, current_cycle)
        important_facts = await self._get_important_facts(conn, current_cycle)
        location_facts = await self._get_location_facts(
            conn, current_location_name, current_cycle
        )
        npc_facts = await self._get_npc_facts(
            conn, [n.name for n in npcs_present], current_cycle
        )
        cycle_summaries = await self._get_cycle_summaries(conn, current_cycle, limit=7)
        recent_messages = await self._get_recent_messages(conn, limit=5)

        return NarrationContext(
            current_cycle=current_cycle,
            current_time=current_time,
            current_date=date,
            current_location=current_location,
            connected_locations=connected_locations,
            protagonist=protagonist,
            inventory=inventory,
            personal_ai=personal_ai,
            npcs_present=npcs_present,
            npcs_relevant=npcs_relevant,
            active_commitments=commitments,
            upcoming_events=events,
            recent_important_facts=important_facts,
            location_relevant_facts=location_facts,
            npc_relevant_facts=npc_facts,
            cycle_summaries=cycle_summaries,
            recent_messages=recent_messages,
            player_input=player_input,
            world_name=world_info.get("name", "Station"),
            world_atmosphere=world_info.get("atmosphere", ""),
            tone_notes=world_info.get("tone_notes", ""),
        )

    # =========================================================================
    # WORLD
    # =========================================================================

    async def _get_world_info(self, conn: Connection) -> dict:
        """Get world info (top-level location without parent)"""
        row = await conn.fetchrow(
            """
            SELECT e.name, 
                   get_attribute(e.id, 'atmosphere') as atmosphere,
                   get_attribute(e.id, 'description') as description
            FROM entities e
            JOIN entity_locations el ON el.entity_id = e.id
            WHERE e.game_id = $1 
              AND e.type = 'location'
              AND e.removed_cycle IS NULL
              AND el.parent_location_id IS NULL
            LIMIT 1
            """,
            self.game_id,
        )
        return dict(row) if row else {}

    async def _get_date_info(self, conn: Connection, cycle: int) -> str:
        """Get current date from cycle_summaries"""
        row = await conn.fetchrow(
            """
            SELECT date FROM cycle_summaries
            WHERE game_id = $1 AND cycle <= $2 AND date IS NOT NULL
            ORDER BY cycle DESC LIMIT 1
            """,
            self.game_id,
            cycle,
        )
        return row["date"] if row else "Lundi 1er janvier 2875"

    # =========================================================================
    # PROTAGONIST
    # =========================================================================

    async def _get_protagonist_state(self, conn: Connection) -> ProtagonistState:
        """Get protagonist state using v_protagonist view"""
        row = await conn.fetchrow(
            "SELECT * FROM v_protagonist WHERE game_id = $1 LIMIT 1",
            self.game_id,
        )

        if not row:
            raise ValueError("Protagonist not found")

        protagonist_id = row["id"]

        # Get skills
        skills = await conn.fetch(
            "SELECT name, level FROM skills WHERE entity_id = $1 AND end_cycle IS NULL",
            protagonist_id,
        )
        skills_str = [f"{s['name']} ({s['level']})" for s in skills]

        # Get employer
        employer = await conn.fetchval(
            """
            SELECT e2.name FROM relations r
            JOIN entities e2 ON e2.id = r.target_id
            WHERE r.source_id = $1 AND r.type = 'employed_by' AND r.end_cycle IS NULL
            """,
            protagonist_id,
        )

        # Get occupation
        occupation = None
        if employer:
            occupation = await conn.fetchval(
                """
                SELECT rp.position FROM relations r
                JOIN relations_professional rp ON rp.relation_id = r.id
                WHERE r.source_id = $1 AND r.type = 'employed_by' AND r.end_cycle IS NULL
                """,
                protagonist_id,
            )

        hobbies = []
        if row["hobbies"]:
            try:
                hobbies = json.loads(row["hobbies"])
            except:
                pass

        return ProtagonistState(
            name=row["name"],
            credits=row["credits"] or 0,
            energy=GaugeState(value=float(row["energy"] or 3)),
            morale=GaugeState(value=float(row["morale"] or 3)),
            health=GaugeState(value=float(row["health"] or 4)),
            skills=skills_str,
            hobbies=hobbies if isinstance(hobbies, list) else [],
            current_occupation=occupation,
            employer=employer,
        )

    async def _get_inventory(self, conn: Connection) -> list[InventoryItem]:
        """Get protagonist inventory using v_inventory view"""
        rows = await conn.fetch(
            "SELECT * FROM v_inventory WHERE game_id = $1",
            self.game_id,
        )

        items = []
        for r in rows:
            # Check emotional significance
            emotional = await conn.fetchval(
                """
                SELECT value FROM attributes 
                WHERE entity_id = $1 AND key = 'emotional_significance' AND end_cycle IS NULL
                """,
                r["object_id"],
            )
            items.append(
                InventoryItem(
                    name=r["object_name"],
                    category=r["category"] or "misc",
                    quantity=r["quantity"] or 1,
                    emotional=bool(emotional),
                )
            )
        return items

    async def _get_personal_ai(self, conn: Connection) -> PersonalAISummary | None:
        """Get personal AI using v_ais view"""
        row = await conn.fetchrow(
            "SELECT * FROM v_ais WHERE game_id = $1 LIMIT 1",
            self.game_id,
        )

        if not row:
            return None

        traits = []
        if row["traits"]:
            try:
                traits = json.loads(row["traits"])
            except:
                pass

        return PersonalAISummary(
            name=row["name"],
            voice_description=row["voice"],
            personality_traits=traits if isinstance(traits, list) else [],
            quirk=row["quirk"],
        )

    # =========================================================================
    # LOCATIONS
    # =========================================================================

    async def _get_location(self, conn: Connection, name: str) -> LocationSummary:
        """Get a location using v_locations view"""
        row = await conn.fetchrow(
            "SELECT * FROM v_locations WHERE game_id = $1 AND LOWER(name) = LOWER($2)",
            self.game_id,
            name,
        )

        if not row:
            return LocationSummary(
                name=name, type="unknown", sector="unknown", atmosphere="", current=True
            )

        return LocationSummary(
            name=row["name"],
            type=row["location_type"] or "unknown",
            sector=row["sector"] or "unknown",
            atmosphere=row["atmosphere"] or "",
            accessible=row["accessible"] if row["accessible"] is not None else True,
            current=True,
        )

    async def _get_connected_locations(
        self, conn: Connection, current_location: str
    ) -> list[LocationSummary]:
        """Get accessible locations from current location"""
        rows = await conn.fetch(
            """
            WITH current AS (
                SELECT e.id, 
                       get_attribute(e.id, 'sector') as sector,
                       el.parent_location_id
                FROM entities e
                JOIN entity_locations el ON el.entity_id = e.id
                WHERE e.game_id = $1 AND LOWER(e.name) = LOWER($2)
            )
            SELECT DISTINCT v.* FROM v_locations v
            CROSS JOIN current c
            WHERE v.game_id = $1
              AND v.accessible = true
              AND LOWER(v.name) != LOWER($2)
              AND (
                  v.sector = c.sector
                  OR v.parent_location_id = c.id
                  OR v.id = c.parent_location_id
              )
            LIMIT 10
            """,
            self.game_id,
            current_location,
        )

        return [
            LocationSummary(
                name=r["name"],
                type=r["location_type"] or "unknown",
                sector=r["sector"] or "unknown",
                atmosphere=r["atmosphere"] or "",
                accessible=True,
            )
            for r in rows
        ]

    # =========================================================================
    # NPCs
    # =========================================================================

    async def _get_npcs_at_location(
        self, conn: Connection, location_name: str, current_time: str
    ) -> list[NPCSummary]:
        """Get NPCs at a location using v_characters view"""
        rows = await conn.fetch(
            """
            SELECT DISTINCT v.*, rs.level as rel_level, rs.context as rel_context
            FROM v_characters v
            JOIN relations r ON r.source_id = v.id
            JOIN entities loc ON loc.id = r.target_id
            LEFT JOIN relations r_prot ON r_prot.target_id = v.id 
                AND r_prot.type IN ('knows', 'friend_of', 'romantic')
                AND r_prot.end_cycle IS NULL
            LEFT JOIN relations_social rs ON rs.relation_id = r_prot.id
            WHERE v.game_id = $1
              AND LOWER(loc.name) = LOWER($2)
              AND r.type IN ('works_at', 'lives_at', 'frequents')
              AND r.end_cycle IS NULL
            LIMIT 5
            """,
            self.game_id,
            location_name,
        )

        return [self._row_to_npc_summary(r) for r in rows]

    async def _get_relevant_npcs(
        self, conn: Connection, current_cycle: int
    ) -> list[NPCSummary]:
        """Get relevant NPCs (known, involved in arcs)"""
        rows = await conn.fetch(
            """
            SELECT DISTINCT v.*, rs.level as rel_level, rs.context as rel_context
            FROM v_characters v
            JOIN relations r ON r.target_id = v.id
            JOIN entities prot ON prot.id = r.source_id AND prot.type = 'protagonist'
            LEFT JOIN relations_social rs ON rs.relation_id = r.id
            WHERE v.game_id = $1
              AND r.type IN ('knows', 'friend_of', 'romantic', 'colleague_of')
              AND r.end_cycle IS NULL
              AND r.known_by_protagonist = true
            ORDER BY rs.level DESC NULLS LAST
            LIMIT 8
            """,
            self.game_id,
        )

        return [self._row_to_npc_summary(r) for r in rows]

    def _row_to_npc_summary(self, row) -> NPCSummary:
        """Convert row to NPCSummary"""
        display_name = row["name"]
        if not row.get("known_by_protagonist", True):
            display_name = row.get("unknown_name") or "Inconnu(e)"

        traits = []
        if row.get("traits"):
            try:
                traits = json.loads(row["traits"])
            except:
                pass

        arcs = []
        if row.get("arcs"):
            try:
                arcs_raw = json.loads(row["arcs"])
                for arc in arcs_raw[:2]:
                    arcs.append(
                        ArcSummary(
                            domain=ArcDomain(arc.get("domain", "personal")),
                            title=arc.get("title", ""),
                            situation_brief=arc.get("situation", "")[:100],
                            intensity=arc.get("intensity", 3),
                        )
                    )
            except:
                pass

        return NPCSummary(
            name=display_name,
            occupation=row.get("occupation") or "inconnu",
            species=row.get("species") or "human",
            traits=traits[:3] if isinstance(traits, list) else [],
            relationship_to_protagonist=row.get("rel_context", "")[:50]
            if row.get("rel_context")
            else None,
            relationship_level=row.get("rel_level"),
            active_arcs=arcs,
        )

    # =========================================================================
    # COMMITMENTS & EVENTS
    # =========================================================================

    async def _get_active_commitments(
        self, conn: Connection
    ) -> list[CommitmentSummary]:
        """Get active commitments using v_active_commitments view"""
        rows = await conn.fetch(
            "SELECT * FROM v_active_commitments WHERE game_id = $1 LIMIT 10",
            self.game_id,
        )

        return [
            CommitmentSummary(
                type=r["type"],
                title=r["description"][:50] if r["description"] else "",
                description_brief=r["description"][:150] if r["description"] else "",
                involved=[e["name"] for e in (r["entities"] or []) if e.get("name")],
                deadline_cycle=r["deadline_cycle"],
            )
            for r in rows
        ]

    async def _get_upcoming_events(
        self, conn: Connection, current_cycle: int
    ) -> list[EventSummary]:
        """Get upcoming events using v_upcoming_events view"""
        rows = await conn.fetch(
            """
            SELECT * FROM v_upcoming_events 
            WHERE game_id = $1 AND planned_cycle >= $2
            ORDER BY planned_cycle LIMIT 5
            """,
            self.game_id,
            current_cycle,
        )

        return [
            EventSummary(
                title=r["title"],
                planned_cycle=r["planned_cycle"],
                planned_time=r["time"],
                location=r["location_name"],
                participants=[p for p in (r["participants"] or []) if p],
                type=r["type"],
            )
            for r in rows
        ]

    # =========================================================================
    # FACTS
    # =========================================================================

    async def _get_important_facts(
        self, conn: Connection, current_cycle: int, lookback: int = 5
    ) -> list[RecentFact]:
        """Get important recent facts"""
        rows = await conn.fetch(
            """
            SELECT * FROM v_recent_facts
            WHERE game_id = $1 
              AND cycle BETWEEN $2 AND $3
              AND importance >= 4
            ORDER BY importance DESC, cycle DESC
            LIMIT 10
            """,
            self.game_id,
            current_cycle - lookback,
            current_cycle,
        )

        return [
            RecentFact(
                cycle=r["cycle"],
                description=r["description"][:200],
                importance=r["importance"],
                involves=[
                    p["name"] for p in (r["participants"] or []) if p.get("name")
                ],
            )
            for r in rows
        ]

    async def _get_location_facts(
        self,
        conn: Connection,
        location_name: str,
        current_cycle: int,
        lookback: int = 10,
    ) -> list[RecentFact]:
        """Get facts related to a location"""
        rows = await conn.fetch(
            """
            SELECT * FROM v_recent_facts
            WHERE game_id = $1 
              AND location_name = $2
              AND cycle >= $3
            ORDER BY cycle DESC LIMIT 5
            """,
            self.game_id,
            location_name,
            current_cycle - lookback,
        )

        return [
            RecentFact(
                cycle=r["cycle"],
                description=r["description"][:200],
                importance=r["importance"],
            )
            for r in rows
        ]

    async def _get_npc_facts(
        self,
        conn: Connection,
        npc_names: list[str],
        current_cycle: int,
        lookback: int = 10,
    ) -> list[RecentFact]:
        """Get facts involving specific NPCs"""
        if not npc_names:
            return []

        rows = await conn.fetch(
            """
            SELECT DISTINCT f.* FROM v_recent_facts f
            WHERE f.game_id = $1 
              AND f.cycle >= $2
              AND EXISTS (
                  SELECT 1 FROM jsonb_array_elements(f.participants) p
                  WHERE LOWER(p->>'name') = ANY($3)
              )
            ORDER BY f.cycle DESC LIMIT 8
            """,
            self.game_id,
            current_cycle - lookback,
            [n.lower() for n in npc_names],
        )

        return [
            RecentFact(
                cycle=r["cycle"],
                description=r["description"][:200],
                importance=r["importance"],
                involves=[
                    p["name"] for p in (r["participants"] or []) if p.get("name")
                ],
            )
            for r in rows
        ]

    # =========================================================================
    # HISTORY
    # =========================================================================

    async def _get_cycle_summaries(
        self, conn: Connection, current_cycle: int, limit: int = 7
    ) -> list[str]:
        """Get summaries of recent cycles"""
        rows = await conn.fetch(
            """
            SELECT cycle, date, summary FROM cycle_summaries
            WHERE game_id = $1 AND cycle < $2 AND summary IS NOT NULL
            ORDER BY cycle DESC LIMIT $3
            """,
            self.game_id,
            current_cycle,
            limit,
        )

        return [
            f"Cycle {r['cycle']} ({r['date'] or f'Cycle {r['cycle']}'}) : {r['summary']}"
            for r in reversed(rows)
        ]

    async def _get_recent_messages(
        self, conn: Connection, limit: int = 5
    ) -> list[MessageSummary]:
        """Get summaries of recent messages"""
        rows = await conn.fetch(
            """
            SELECT role, summary, cycle FROM chat_messages
            WHERE game_id = $1 AND summary IS NOT NULL
            ORDER BY created_at DESC LIMIT $2
            """,
            self.game_id,
            limit,
        )

        return [
            MessageSummary(role=r["role"], summary=r["summary"][:200], cycle=r["cycle"])
            for r in reversed(rows)
        ]

    # =========================================================================
    # UTILITIES
    # =========================================================================

    async def get_known_entity_names(self, conn: Connection) -> list[str]:
        """Get all known entity names (for extractor)"""
        rows = await conn.fetch(
            "SELECT name FROM entities WHERE game_id = $1 AND removed_cycle IS NULL ORDER BY name",
            self.game_id,
        )
        return [r["name"] for r in rows]

    async def get_known_entity_display_names(self, conn: Connection) -> list[dict]:
        """Get entities with display names for narrator"""
        rows = await conn.fetch(
            """
            SELECT name, known_by_protagonist, unknown_name, type
            FROM entities WHERE game_id = $1 AND removed_cycle IS NULL ORDER BY name
            """,
            self.game_id,
        )

        return [
            {
                "real_name": r["name"],
                "display_name": r["name"]
                if r["known_by_protagonist"]
                else (r["unknown_name"] or "Inconnu(e)"),
                "known": r["known_by_protagonist"],
                "type": r["type"],
            }
            for r in rows
        ]
