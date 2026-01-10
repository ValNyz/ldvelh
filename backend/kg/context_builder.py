"""
LDVELH - Context Builder
Construit le contexte de narration depuis la base de données
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
)
from schema import ArcDomain

if TYPE_CHECKING:
    from asyncpg import Connection


class ContextBuilder:
    """Construit le NarrationContext depuis la base de données"""

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
        """Construit le contexte complet pour le narrateur"""

        # Récupérer les infos de base du monde
        world_info = await self._get_world_info(conn)

        # Récupérer le cycle summary actuel pour date/day
        day_info = await self._get_day_info(conn, current_cycle)

        # Protagoniste
        protagonist = await self._get_protagonist_state(conn)
        inventory = await self._get_inventory(conn)

        # Lieu actuel
        current_location = await self._get_location(conn, current_location_name)
        connected_locations = await self._get_connected_locations(
            conn, current_location_name
        )

        # PNJs
        npcs_present = await self._get_npcs_at_location(
            conn, current_location_name, current_time
        )
        npcs_relevant = await self._get_relevant_npcs(conn, current_cycle)

        # Narratif
        commitments = await self._get_active_commitments(conn)
        events = await self._get_upcoming_events(conn, current_cycle)

        # Faits
        important_facts = await self._get_important_facts(conn, current_cycle)
        location_facts = await self._get_location_facts(
            conn, current_location_name, current_cycle
        )
        npc_facts = await self._get_npc_facts(
            conn, [n.name for n in npcs_present], current_cycle
        )

        # Historique
        cycle_summaries = await self._get_cycle_summaries(conn, current_cycle, limit=7)
        recent_messages = await self._get_recent_messages(conn, limit=5)

        return NarrationContext(
            # Temps
            current_cycle=current_cycle,
            current_day=day_info.get("day", current_cycle),
            current_date=day_info.get("date", f"Jour {current_cycle}"),
            current_time=current_time,
            # Espace
            current_location=current_location,
            connected_locations=connected_locations,
            # Protagoniste
            protagonist=protagonist,
            inventory=inventory,
            # PNJs
            npcs_present=npcs_present,
            npcs_relevant=npcs_relevant,
            # Narratif
            active_commitments=commitments,
            upcoming_events=events,
            # Faits
            recent_important_facts=important_facts,
            location_relevant_facts=location_facts,
            npc_relevant_facts=npc_facts,
            # Historique
            cycle_summaries=cycle_summaries,
            recent_messages=recent_messages,
            # Input
            player_input=player_input,
            # Meta
            world_name=world_info.get("name", "Station"),
            world_atmosphere=world_info.get("atmosphere", ""),
            tone_notes=world_info.get("tone_notes", ""),
        )

    # =========================================================================
    # WORLD
    # =========================================================================

    async def _get_world_info(self, conn: Connection) -> dict:
        """Récupère les infos du monde (station)"""
        row = await conn.fetchrow(
            """
            SELECT e.name, a1.value as atmosphere, a2.value as description
            FROM entities e
            LEFT JOIN attributes a1 ON a1.entity_id = e.id AND a1.key = 'atmosphere' AND a1.end_cycle IS NULL
            LEFT JOIN attributes a2 ON a2.entity_id = e.id AND a2.key = 'description' AND a2.end_cycle IS NULL
            WHERE e.game_id = $1 
            AND e.type = 'location'
            AND e.removed_cycle IS NULL
            AND NOT EXISTS (
                SELECT 1 FROM entity_locations el 
                WHERE el.entity_id = e.id AND el.parent_location_id IS NOT NULL
            )
            LIMIT 1
        """,
            self.game_id,
        )

        return dict(row) if row else {}

    async def _get_day_info(self, conn: Connection, cycle: int) -> dict:
        """Récupère les infos du jour (depuis cycle_summaries)"""
        row = await conn.fetchrow(
            """
            SELECT day, date
            FROM cycle_summaries
            WHERE game_id = $1 AND cycle <= $2 AND day IS NOT NULL
            ORDER BY cycle DESC
            LIMIT 1
        """,
            self.game_id,
            cycle,
        )

        if row:
            return {"day": row["day"], "date": row["date"]}

        # Fallback : pas encore de cycle_summaries
        return {"day": "Lundi", "date": "Jour 1"}

    # =========================================================================
    # PROTAGONIST
    # =========================================================================

    async def _get_protagonist_state(self, conn: Connection) -> ProtagonistState:
        """Récupère l'état du protagoniste"""
        # Récupérer l'entité protagoniste
        row = await conn.fetchrow(
            """
            SELECT e.id, e.name, ep.origin_location, ep.departure_reason
            FROM entities e
            JOIN entity_protagonists ep ON ep.entity_id = e.id
            WHERE e.game_id = $1 AND e.type = 'protagonist' AND e.removed_cycle IS NULL
        """,
            self.game_id,
        )

        if not row:
            raise ValueError("Protagonist not found")

        protagonist_id = row["id"]
        name = row["name"]

        # Récupérer les attributs
        attrs = await conn.fetch(
            """
            SELECT key, value
            FROM attributes
            WHERE entity_id = $1 AND end_cycle IS NULL
        """,
            protagonist_id,
        )

        attr_dict = {a["key"]: a["value"] for a in attrs}

        # Récupérer les skills
        skills = await conn.fetch(
            """
            SELECT name, level
            FROM skills
            WHERE entity_id = $1 AND end_cycle IS NULL
        """,
            protagonist_id,
        )

        skills_str = [f"{s['name']} ({s['level']})" for s in skills]

        # Récupérer l'employeur
        employer = await conn.fetchval(
            """
            SELECT e2.name
            FROM relations r
            JOIN entities e2 ON e2.id = r.target_id
            WHERE r.source_id = $1 
            AND r.type = 'employed_by' 
            AND r.end_cycle IS NULL
        """,
            protagonist_id,
        )

        # Récupérer le poste
        occupation = None
        if employer:
            occupation = await conn.fetchval(
                """
                SELECT rp.position
                FROM relations r
                JOIN relations_professional rp ON rp.relation_id = r.id
                WHERE r.source_id = $1 AND r.type = 'employed_by' AND r.end_cycle IS NULL
            """,
                protagonist_id,
            )

        hobbies = json.loads(attr_dict.get("hobbies", "[]"))

        return ProtagonistState(
            name=name,
            credits=int(attr_dict.get("credits", 0)),
            energy=GaugeState(value=float(attr_dict.get("energy", 3))),
            morale=GaugeState(value=float(attr_dict.get("morale", 3))),
            health=GaugeState(value=float(attr_dict.get("health", 4))),
            skills=skills_str,
            hobbies=hobbies if isinstance(hobbies, list) else [],
            current_occupation=occupation,
            employer=employer,
        )

    async def _get_inventory(self, conn: Connection) -> list[InventoryItem]:
        """Récupère l'inventaire du protagoniste"""
        rows = await conn.fetch(
            """
            SELECT e2.name, eo.category, ro.quantity,
                   a.value as emotional
            FROM entities e
            JOIN relations r ON r.source_id = e.id
            JOIN entities e2 ON e2.id = r.target_id
            JOIN entity_objects eo ON eo.entity_id = e2.id
            LEFT JOIN relations_ownership ro ON ro.relation_id = r.id
            LEFT JOIN attributes a ON a.entity_id = e2.id 
                AND a.key = 'emotional_significance' AND a.end_cycle IS NULL
            WHERE e.game_id = $1 
            AND e.type = 'protagonist' 
            AND e.removed_cycle IS NULL
            AND r.type = 'owns' 
            AND r.end_cycle IS NULL
            AND e2.removed_cycle IS NULL
        """,
            self.game_id,
        )

        return [
            InventoryItem(
                name=r["name"],
                category=r["category"] or "misc",
                quantity=r["quantity"] or 1,
                emotional=bool(r["emotional"]),
            )
            for r in rows
        ]

    # =========================================================================
    # LOCATIONS
    # =========================================================================

    async def _get_location(self, conn: Connection, name: str) -> LocationSummary:
        """Récupère un lieu par son nom"""
        row = await conn.fetchrow(
            """
            SELECT e.name, el.location_type, el.sector, el.accessible,
                   a.value as atmosphere
            FROM entities e
            JOIN entity_locations el ON el.entity_id = e.id
            LEFT JOIN attributes a ON a.entity_id = e.id 
                AND a.key = 'atmosphere' AND a.end_cycle IS NULL
            WHERE e.game_id = $1 
            AND LOWER(e.name) = LOWER($2)
            AND e.removed_cycle IS NULL
        """,
            self.game_id,
            name,
        )

        if not row:
            # Fallback
            return LocationSummary(
                name=name, type="unknown", sector="unknown", atmosphere="", current=True
            )

        return LocationSummary(
            name=row["name"],
            type=row["location_type"] or "unknown",
            sector=row["sector"] or "unknown",
            atmosphere=row["atmosphere"] or "",
            accessible=row["accessible"],
            current=True,
        )

    async def _get_connected_locations(
        self, conn: Connection, current_location: str
    ) -> list[LocationSummary]:
        """Récupère les lieux accessibles depuis le lieu actuel"""
        # Lieux dans le même secteur + parent + enfants
        rows = await conn.fetch(
            """
            WITH current AS (
                SELECT e.id, el.sector, el.parent_location_id
                FROM entities e
                JOIN entity_locations el ON el.entity_id = e.id
                WHERE e.game_id = $1 AND LOWER(e.name) = LOWER($2)
            )
            SELECT DISTINCT e.name, el.location_type, el.sector, el.accessible,
                   a.value as atmosphere
            FROM entities e
            JOIN entity_locations el ON el.entity_id = e.id
            LEFT JOIN attributes a ON a.entity_id = e.id 
                AND a.key = 'atmosphere' AND a.end_cycle IS NULL
            CROSS JOIN current c
            WHERE e.game_id = $1
            AND e.removed_cycle IS NULL
            AND el.accessible = true
            AND LOWER(e.name) != LOWER($2)
            AND (
                el.sector = c.sector
                OR el.parent_location_id = c.id
                OR el.entity_id = c.parent_location_id
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
        """Récupère les PNJs présents à un lieu (basé sur works_at, lives_at, frequents)"""
        rows = await conn.fetch(
            """
            SELECT DISTINCT e.id, e.name, ec.species, ec.gender, ec.traits,
                   a_occ.value as occupation,
                   rs.level as rel_level, rs.context as rel_context,
                   a_arcs.value as arcs
            FROM entities e
            JOIN entity_characters ec ON ec.entity_id = e.id
            JOIN relations r ON r.source_id = e.id
            JOIN entities loc ON loc.id = r.target_id
            LEFT JOIN relations r_prot ON r_prot.target_id = e.id 
                AND r_prot.type IN ('knows', 'friend_of', 'romantic')
                AND r_prot.end_cycle IS NULL
            LEFT JOIN relations_social rs ON rs.relation_id = r_prot.id
            LEFT JOIN attributes a_occ ON a_occ.entity_id = e.id 
                AND a_occ.key = 'occupation' AND a_occ.end_cycle IS NULL
            LEFT JOIN attributes a_arcs ON a_arcs.entity_id = e.id 
                AND a_arcs.key = 'arcs' AND a_arcs.end_cycle IS NULL
            WHERE e.game_id = $1
            AND LOWER(loc.name) = LOWER($2)
            AND r.type IN ('works_at', 'lives_at', 'frequents')
            AND r.end_cycle IS NULL
            AND e.removed_cycle IS NULL
            LIMIT 5
        """,
            self.game_id,
            location_name,
        )

        return [self._row_to_npc_summary(r) for r in rows]

    async def _get_relevant_npcs(
        self, conn: Connection, current_cycle: int
    ) -> list[NPCSummary]:
        """Récupère les PNJs pertinents (connus, impliqués dans des arcs actifs)"""
        rows = await conn.fetch(
            """
            SELECT DISTINCT e.id, e.name, ec.species, ec.gender, ec.traits,
                   a_occ.value as occupation,
                   rs.level as rel_level, rs.context as rel_context,
                   a_arcs.value as arcs
            FROM entities e
            JOIN entity_characters ec ON ec.entity_id = e.id
            JOIN relations r ON r.target_id = e.id
            JOIN entities prot ON prot.id = r.source_id AND prot.type = 'protagonist'
            LEFT JOIN relations_social rs ON rs.relation_id = r.id
            LEFT JOIN attributes a_occ ON a_occ.entity_id = e.id 
                AND a_occ.key = 'occupation' AND a_occ.end_cycle IS NULL
            LEFT JOIN attributes a_arcs ON a_arcs.entity_id = e.id 
                AND a_arcs.key = 'arcs' AND a_arcs.end_cycle IS NULL
            WHERE e.game_id = $1
            AND r.type IN ('knows', 'friend_of', 'romantic', 'colleague_of')
            AND r.end_cycle IS NULL
            AND e.removed_cycle IS NULL
            ORDER BY rel_level DESC NULLS LAST
            LIMIT 8
        """,
            self.game_id,
        )

        return [self._row_to_npc_summary(r) for r in rows]

    def _row_to_npc_summary(self, row) -> NPCSummary:
        """Convertit une row en NPCSummary"""
        traits = json.loads(row["traits"]) if row["traits"] else []
        arcs_raw = json.loads(row["arcs"]) if row["arcs"] else []

        arcs = []
        for arc in arcs_raw[:2]:  # Max 2 arcs
            try:
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

        rel_type = None
        if row.get("rel_context"):
            rel_type = row["rel_context"][:50]

        return NPCSummary(
            name=row["name"],
            occupation=row["occupation"] or "inconnu",
            species=row["species"] or "human",
            traits=traits[:3] if isinstance(traits, list) else [],
            relationship_to_protagonist=rel_type,
            relationship_level=row.get("rel_level"),
            active_arcs=arcs,
        )

    # =========================================================================
    # COMMITMENTS & EVENTS
    # =========================================================================

    async def _get_active_commitments(
        self, conn: Connection
    ) -> list[CommitmentSummary]:
        """Récupère les engagements narratifs actifs"""
        rows = await conn.fetch(
            """
            SELECT c.type, c.description, c.deadline_cycle,
                   array_agg(e.name) as involved
            FROM commitments c
            LEFT JOIN commitment_entities ce ON ce.commitment_id = c.id
            LEFT JOIN entities e ON e.id = ce.entity_id
            WHERE c.game_id = $1 AND c.resolved = false
            GROUP BY c.id, c.type, c.description, c.deadline_cycle
            ORDER BY c.deadline_cycle NULLS LAST
            LIMIT 10
        """,
            self.game_id,
        )

        return [
            CommitmentSummary(
                type=r["type"],
                title=r["description"][:50] if r["description"] else "",
                description_brief=r["description"][:150] if r["description"] else "",
                involved=[n for n in (r["involved"] or []) if n],
                deadline_cycle=r["deadline_cycle"],
            )
            for r in rows
        ]

    async def _get_upcoming_events(
        self, conn: Connection, current_cycle: int
    ) -> list[EventSummary]:
        """Récupère les événements à venir"""
        rows = await conn.fetch(
            """
            SELECT ev.title, ev.type, ev.planned_cycle, ev.moment,
                   loc.name as location,
                   array_agg(e.name) as participants
            FROM events ev
            LEFT JOIN entities loc ON loc.id = ev.location_id
            LEFT JOIN event_participants ep ON ep.event_id = ev.id
            LEFT JOIN entities e ON e.id = ep.entity_id
            WHERE ev.game_id = $1 
            AND ev.planned_cycle >= $2
            AND ev.completed = false AND ev.cancelled = false
            GROUP BY ev.id, ev.title, ev.type, ev.planned_cycle, ev.moment, loc.name
            ORDER BY ev.planned_cycle
            LIMIT 5
        """,
            self.game_id,
            current_cycle,
        )

        return [
            EventSummary(
                title=r["title"],
                planned_cycle=r["planned_cycle"],
                planned_time=r["moment"],
                location=r["location"],
                participants=[n for n in (r["participants"] or []) if n],
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
        """Récupère les faits importants récents"""
        rows = await conn.fetch(
            """
            SELECT f.cycle, f.description, f.importance,
                   array_agg(e.name) as involves
            FROM facts f
            LEFT JOIN fact_participants fp ON fp.fact_id = f.id
            LEFT JOIN entities e ON e.id = fp.entity_id
            WHERE f.game_id = $1 
            AND f.cycle >= $2
            AND f.importance >= 4
            GROUP BY f.id, f.cycle, f.description, f.importance
            ORDER BY f.importance DESC, f.cycle DESC
            LIMIT 10
        """,
            self.game_id,
            current_cycle - lookback,
        )

        return [
            RecentFact(
                cycle=r["cycle"],
                description=r["description"][:200],
                importance=r["importance"],
                involves=[n for n in (r["involves"] or []) if n],
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
        """Récupère les faits liés à un lieu"""
        rows = await conn.fetch(
            """
            SELECT f.cycle, f.description, f.importance
            FROM facts f
            JOIN entities loc ON loc.id = f.location_id
            WHERE f.game_id = $1 
            AND LOWER(loc.name) = LOWER($2)
            AND f.cycle >= $3
            ORDER BY f.cycle DESC
            LIMIT 5
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
        """Récupère les faits liés à des PNJs"""
        if not npc_names:
            return []

        rows = await conn.fetch(
            """
            SELECT DISTINCT f.cycle, f.description, f.importance,
                   array_agg(e.name) as involves
            FROM facts f
            JOIN fact_participants fp ON fp.fact_id = f.id
            JOIN entities e ON e.id = fp.entity_id
            WHERE f.game_id = $1 
            AND LOWER(e.name) = ANY($2)
            AND f.cycle >= $3
            GROUP BY f.id, f.cycle, f.description, f.importance
            ORDER BY f.cycle DESC
            LIMIT 8
        """,
            self.game_id,
            [n.lower() for n in npc_names],
            current_cycle - lookback,
        )

        return [
            RecentFact(
                cycle=r["cycle"],
                description=r["description"][:200],
                importance=r["importance"],
                involves=[n for n in (r["involves"] or []) if n],
            )
            for r in rows
        ]

    # =========================================================================
    # HISTORY
    # =========================================================================

    async def _get_cycle_summaries(
        self, conn: Connection, current_cycle: int, limit: int = 7
    ) -> list[str]:
        """Récupère les résumés des derniers cycles"""
        rows = await conn.fetch(
            """
            SELECT cycle, day, date, summary
            FROM cycle_summaries
            WHERE game_id = $1 AND cycle < $2 AND summary IS NOT NULL
            ORDER BY cycle DESC
            LIMIT $3
        """,
            self.game_id,
            current_cycle,
            limit,
        )

        results = []
        for r in reversed(rows):
            # Formater : "Cycle 3 (Mardi 15 Mars) : résumé..."
            date_str = (
                f"{r['day']} {r['date']}"
                if r["day"] and r["date"]
                else r["date"] or f"Cycle {r['cycle']}"
            )
            results.append(f"Cycle {r['cycle']} ({date_str}) : {r['summary']}")

        return results

    async def _get_recent_messages(
        self, conn: Connection, limit: int = 5
    ) -> list[MessageSummary]:
        """Récupère les résumés des derniers messages"""
        rows = await conn.fetch(
            """
            SELECT role, summary, cycle
            FROM chat_messages
            WHERE game_id = $1 AND summary IS NOT NULL
            ORDER BY created_at DESC
            LIMIT $2
        """,
            self.game_id,
            limit,
        )

        return [
            MessageSummary(
                role=r["role"],
                summary=r["summary"][:200],
                cycle=r["cycle"],
            )
            for r in reversed(rows)
        ]

    # =========================================================================
    # UTILITIES
    # =========================================================================

    async def get_known_entity_names(self, conn: Connection) -> list[str]:
        """Récupère tous les noms d'entités connues (pour l'extracteur)"""
        rows = await conn.fetch(
            """
            SELECT name FROM entities
            WHERE game_id = $1 AND removed_cycle IS NULL
            ORDER BY name
        """,
            self.game_id,
        )

        return [r["name"] for r in rows]
