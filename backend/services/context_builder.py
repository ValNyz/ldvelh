"""
LDVELH - Context Builder Service
Builds narration context from database using KnowledgeGraphReader
"""

from __future__ import annotations
from uuid import UUID
from typing import TYPE_CHECKING

from utils import parse_json
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

from kg.reader import KnowledgeGraphReader

if TYPE_CHECKING:
    from asyncpg import Connection, Pool


class ContextBuilder:
    """Builds NarrationContext from database using KnowledgeGraphReader"""

    def __init__(self, pool: Pool, game_id: UUID):
        self.pool = pool
        self.game_id = game_id
        self.reader = KnowledgeGraphReader(pool, game_id)

    async def build(
        self,
        conn: Connection,
        player_input: str,
        current_cycle: int,
        current_time: str,
        current_location_name: str,
    ) -> NarrationContext:
        """Build complete context for narrator"""

        # World info
        world_info = await self.reader.get_root_location(conn) or {}

        # Date: utilise get_current_date existant
        date = await self.reader.get_current_date(conn) or "Jour 1"

        # Protagonist avec skills
        protagonist = await self._build_protagonist_state(conn)

        # Inventory via vue existante
        inventory = await self._build_inventory(conn)

        # AI companion via méthode existante
        personal_ai = await self._build_personal_ai(conn)

        # Locations
        current_location = await self._build_current_location(
            conn, current_location_name
        )
        connected_locations = await self._build_connected_locations(
            conn, current_location_name
        )

        # NPCs
        npcs_present = await self._build_npcs_at_location(conn, current_location_name)
        npcs_relevant = await self._build_relevant_npcs(conn)

        # Commitments & Events
        commitments = await self._build_commitments(conn)
        events = await self._build_events(conn, current_cycle)

        # Facts (requête unifiée)
        important_facts = await self._build_facts(conn, current_cycle, min_importance=3)
        location_facts = await self._build_facts(
            conn, current_cycle, location_name=current_location_name
        )
        npc_facts = (
            await self._build_facts(
                conn, current_cycle, npc_names=[n.name for n in npcs_present]
            )
            if npcs_present
            else []
        )

        # History
        cycle_summaries = await self._build_cycle_summaries(conn, current_cycle)
        recent_messages = await self._build_recent_messages(conn)

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
    # PROTAGONIST
    # =========================================================================

    async def _build_protagonist_state(self, conn: Connection) -> ProtagonistState:
        """Build protagonist state from reader"""
        row = await self.reader.get_protagonist_with_skills(conn)
        if not row:
            raise ValueError("Protagonist not found")

        hobbies = parse_json(row.get("hobbies"))
        skills_str = [f"{s['name']} ({s['level']})" for s in row.get("skills", [])]

        return ProtagonistState(
            name=row["name"],
            credits=row.get("credits") or 0,
            energy=GaugeState(value=float(row.get("energy") or 3)),
            morale=GaugeState(value=float(row.get("morale") or 3)),
            health=GaugeState(value=float(row.get("health") or 4)),
            skills=skills_str,
            hobbies=hobbies,
            current_occupation=row.get("occupation"),
            employer=row.get("employer"),
        )

    async def _build_inventory(self, conn: Connection) -> list[InventoryItem]:
        """Build inventory from existing get_inventory"""
        rows = await self.reader.get_inventory(conn)
        return [
            InventoryItem(
                name=r["object_name"],
                category=r.get("category") or "misc",
                quantity=r.get("quantity") or 1,
                emotional=bool(r.get("emotional_significance")),
            )
            for r in rows
        ]

    async def _build_personal_ai(self, conn: Connection) -> PersonalAISummary | None:
        """Build AI companion from existing method"""
        row = await self.reader.get_ai_companion(conn)
        if not row:
            return None

        traits = parse_json(row.get("traits"))
        return PersonalAISummary(
            name=row["name"],
            voice_description=row.get("voice"),
            personality_traits=traits,
            quirk=row.get("quirk"),
        )

    # =========================================================================
    # LOCATIONS
    # =========================================================================

    async def _build_current_location(
        self, conn: Connection, name: str
    ) -> LocationSummary:
        """Build current location summary"""
        row = await self.reader.get_location_details(conn, name)
        if not row:
            return LocationSummary(
                name=name, type="unknown", sector="unknown", atmosphere="", current=True
            )
        return LocationSummary(
            name=row["name"],
            type=row.get("location_type") or "unknown",
            sector=row.get("sector") or "unknown",
            atmosphere=row.get("atmosphere") or "",
            accessible=row.get("accessible", True),
            current=True,
        )

    async def _build_connected_locations(
        self, conn: Connection, current_location: str
    ) -> list[LocationSummary]:
        """Build connected locations list"""
        rows = await self.reader.get_sibling_locations(conn, current_location)
        return [
            LocationSummary(
                name=r["name"],
                type=r.get("location_type") or "unknown",
                sector=r.get("sector") or "unknown",
                atmosphere=r.get("atmosphere") or "",
                accessible=True,
            )
            for r in rows
        ]

    # =========================================================================
    # NPCs
    # =========================================================================

    async def _build_npcs_at_location(
        self, conn: Connection, location_name: str
    ) -> list[NPCSummary]:
        """Build NPCs at location"""
        rows = await self.reader.get_npcs_at_location(conn, location_name)
        return [self._row_to_npc_summary(r) for r in rows]

    async def _build_relevant_npcs(self, conn: Connection) -> list[NPCSummary]:
        """Build relevant NPCs (highest relationship)"""
        rows = await self.reader.get_top_related_npcs(conn, limit=5)
        return [self._row_to_npc_summary(r) for r in rows]

    def _row_to_npc_summary(self, row: dict) -> NPCSummary:
        """Convert DB row to NPCSummary"""
        display_name = row["name"]
        if not row.get("known_by_protagonist", True):
            display_name = row.get("unknown_name") or "Inconnu(e)"

        traits = parse_json(row.get("traits"))
        arcs = self._parse_arcs(row.get("arcs"))

        return NPCSummary(
            name=display_name,
            occupation=row.get("occupation") or "inconnu",
            species=row.get("species") or "human",
            traits=traits[:3],
            relationship_to_protagonist=row.get("rel_context", "")[:50]
            if row.get("rel_context")
            else None,
            relationship_level=row.get("rel_level"),
            active_arcs=arcs,
        )

    def _parse_arcs(self, arcs_raw) -> list[ArcSummary]:
        """Parse arcs JSON to ArcSummary list"""
        arcs_list = parse_json(arcs_raw)
        result = []
        for arc in arcs_list[:2]:
            if isinstance(arc, dict):
                try:
                    result.append(
                        ArcSummary(
                            domain=ArcDomain(arc.get("domain", "personal")),
                            title=arc.get("title", ""),
                            situation_brief=arc.get("situation", "")[:100],
                            intensity=arc.get("intensity", 3),
                        )
                    )
                except (ValueError, KeyError):
                    pass
        return result

    # =========================================================================
    # COMMITMENTS & EVENTS
    # =========================================================================

    async def _build_commitments(self, conn: Connection) -> list[CommitmentSummary]:
        """Build commitments from detailed query"""
        rows = await self.reader.get_commitments_detailed(conn)
        result = []
        for r in rows:
            entities_raw = r.get("entities") or []
            involved = [
                e["name"] for e in entities_raw if isinstance(e, dict) and e.get("name")
            ]

            result.append(
                CommitmentSummary(
                    type=r["type"],
                    title=r["description"][:50] if r.get("description") else "",
                    description_brief=r["description"][:150]
                    if r.get("description")
                    else "",
                    involved=involved,
                    deadline_cycle=r.get("deadline_cycle"),
                )
            )
        return result

    async def _build_events(
        self, conn: Connection, current_cycle: int
    ) -> list[EventSummary]:
        """Build events from detailed query"""
        rows = await self.reader.get_events_detailed(conn, current_cycle)
        return [
            EventSummary(
                title=r["title"],
                planned_cycle=r["planned_cycle"],
                planned_time=r.get("time"),
                location=r.get("location_name"),
                participants=[p for p in (r.get("participants") or []) if p],
                type=r["type"],
            )
            for r in rows
        ]

    # =========================================================================
    # FACTS
    # =========================================================================

    async def _build_facts(
        self,
        conn: Connection,
        current_cycle: int,
        min_importance: int = 1,
        location_name: str | None = None,
        npc_names: list[str] | None = None,
        limit: int = 10,
    ) -> list[RecentFact]:
        """Build facts using unified query"""
        rows = await self.reader.get_facts_with_participants(
            conn,
            cycle=current_cycle,
            min_importance=min_importance,
            location_name=location_name,
            npc_names=npc_names,
            limit=limit,
        )
        return [self._row_to_recent_fact(r) for r in rows]

    def _row_to_recent_fact(self, r: dict) -> RecentFact:
        """Convert row to RecentFact"""
        participants = r.get("participants") or []
        involves = [
            p["name"] for p in participants if isinstance(p, dict) and p.get("name")
        ]

        return RecentFact(
            cycle=r["cycle"],
            description=r["description"][:200] if r.get("description") else "",
            importance=r.get("importance", 3),
            involves=involves,
        )

    # =========================================================================
    # HISTORY
    # =========================================================================

    async def _build_cycle_summaries(
        self, conn: Connection, current_cycle: int, limit: int = 7
    ) -> list[str]:
        """Build cycle summaries"""
        rows = await self.reader.get_cycle_summaries(conn, current_cycle, limit)
        return [
            f"Cycle {r['cycle']} ({r['date'] or f'Jour {r['cycle']}'}) : {r['summary']}"
            for r in reversed(rows)
            if r.get("summary")
        ]

    async def _build_recent_messages(
        self, conn: Connection, limit: int = 5
    ) -> list[MessageSummary]:
        """Build recent message summaries"""
        rows = await self.reader.get_message_summaries(conn, limit)
        return [
            MessageSummary(
                role=r["role"],
                summary=r["summary"][:200] if r.get("summary") else "",
                cycle=r["cycle"],
            )
            for r in reversed(rows)
        ]

    # =========================================================================
    # UTILITIES (pour usage externe)
    # =========================================================================

    async def get_known_entity_names(self, conn: Connection) -> list[str]:
        """Get all known entity names"""
        entities = await self.reader.get_entities(conn)
        return [e["name"] for e in entities if e.get("known_by_protagonist", True)]
