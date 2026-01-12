"""
LDVELH - Context Builder Service
Builds narration context from database using KnowledgeGraphReader

Note: Ce fichier va dans services/ (logique métier, pas accès BDD)
"""

from __future__ import annotations
import json
from uuid import UUID
from typing import TYPE_CHECKING

from utils import parse_json_list
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

        world_info = await self._get_world_info(conn)
        date = await self._get_date_info(conn, current_cycle)
        protagonist = await self._get_protagonist_state(conn)
        inventory = await self._get_inventory(conn)
        personal_ai = await self._get_personal_ai(conn)
        current_location = await self._get_location(conn, current_location_name)
        connected_locations = await self._get_connected_locations(
            conn, current_location_name
        )
        npcs_present = await self._get_npcs_at_location(conn, current_location_name)
        npcs_relevant = await self._get_relevant_npcs(conn)
        commitments = await self._get_active_commitments(conn)
        events = await self._get_upcoming_events(conn, current_cycle)
        important_facts = await self._get_important_facts(conn, current_cycle)
        location_facts = await self._get_location_facts(
            conn, current_location_name, current_cycle
        )
        npc_facts = await self._get_npc_facts(
            conn, [n.name for n in npcs_present], current_cycle
        )
        cycle_summaries = await self._get_cycle_summaries(conn, current_cycle)
        recent_messages = await self._get_recent_messages(conn)

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
        """Get world info via reader"""
        row = await self.reader.get_root_location(conn)
        return row or {}

    async def _get_date_info(self, conn: Connection, cycle: int) -> str:
        """Get current date via reader"""
        date = await self.reader.get_date_for_cycle(conn, cycle)
        return date or "Lundi 1er janvier 2875"

    # =========================================================================
    # PROTAGONIST
    # =========================================================================

    async def _get_protagonist_state(self, conn: Connection) -> ProtagonistState:
        """Get protagonist state via reader"""
        row = await self.reader.get_protagonist_full(conn)

        if not row:
            raise ValueError("Protagonist not found")

        skills_str = [f"{s['name']} ({s['level']})" for s in row.get("skills", [])]
        hobbies = parse_json_list(row.get("hobbies"))

        return ProtagonistState(
            name=row["name"],
            credits=row["credits"] or 0,
            energy=GaugeState(value=float(row["energy"] or 3)),
            morale=GaugeState(value=float(row["morale"] or 3)),
            health=GaugeState(value=float(row["health"] or 4)),
            skills=skills_str,
            hobbies=hobbies if isinstance(hobbies, list) else [],
            current_occupation=row.get("occupation"),
            employer=row.get("employer"),
        )

    async def _get_inventory(self, conn: Connection) -> list[InventoryItem]:
        """Get protagonist inventory via reader"""
        rows = await self.reader.get_inventory_with_emotional(conn)

        return [
            InventoryItem(
                name=r["object_name"],
                category=r["category"] or "misc",
                quantity=r["quantity"] or 1,
                emotional=bool(r.get("emotional")),
            )
            for r in rows
        ]

    async def _get_personal_ai(self, conn: Connection) -> PersonalAISummary | None:
        """Get personal AI via reader"""
        row = await self.reader.get_ai_companion(conn)

        if not row:
            return None

        traits = parse_json_list(row.get("traits"))

        return PersonalAISummary(
            name=row["name"],
            voice_description=row.get("voice"),
            personality_traits=traits if isinstance(traits, list) else [],
            quirk=row.get("quirk"),
        )

    # =========================================================================
    # LOCATIONS
    # =========================================================================

    async def _get_location(self, conn: Connection, name: str) -> LocationSummary:
        """Get a location via reader"""
        row = await self.reader.get_location_by_name(conn, name)

        if not row:
            return LocationSummary(
                name=name, type="unknown", sector="unknown", atmosphere="", current=True
            )

        return LocationSummary(
            name=row["name"],
            type=row.get("location_type") or "unknown",
            sector=row.get("sector") or "unknown",
            atmosphere=row.get("atmosphere") or "",
            accessible=row.get("accessible")
            if row.get("accessible") is not None
            else True,
            current=True,
        )

    async def _get_connected_locations(
        self, conn: Connection, current_location: str
    ) -> list[LocationSummary]:
        """Get accessible locations via reader"""
        rows = await self.reader.get_connected_locations(conn, current_location)

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

    async def _get_npcs_at_location(
        self, conn: Connection, location_name: str
    ) -> list[NPCSummary]:
        """Get NPCs at a location via reader"""
        rows = await self.reader.get_npcs_at_location(conn, location_name)
        return [self._row_to_npc_summary(r) for r in rows]

    async def _get_relevant_npcs(self, conn: Connection) -> list[NPCSummary]:
        """Get relevant NPCs via reader"""
        rows = await self.reader.get_relevant_npcs(conn)
        return [self._row_to_npc_summary(r) for r in rows]

    def _row_to_npc_summary(self, row: dict) -> NPCSummary:
        """Convert row to NPCSummary"""
        display_name = row["name"]
        if not row.get("known_by_protagonist", True):
            display_name = row.get("unknown_name") or "Inconnu(e)"

        traits = parse_json_list(row.get("traits"))

        arcs = []
        arcs_raw = parse_json_list(row.get("arcs"))
        for arc in arcs_raw[:2]:
            if isinstance(arc, dict):
                try:
                    arcs.append(
                        ArcSummary(
                            domain=ArcDomain(arc.get("domain", "personal")),
                            title=arc.get("title", ""),
                            situation_brief=arc.get("situation", "")[:100],
                            intensity=arc.get("intensity", 3),
                        )
                    )
                except (ValueError, KeyError):
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
        """Get active commitments via reader"""
        rows = await self.reader.get_active_commitments_full(conn)

        result = []
        for r in rows:
            entities_raw = r.get("entities") or []
            involved = []

            for e in entities_raw:
                if isinstance(e, str):
                    try:
                        e = json.loads(e)
                    except (json.JSONDecodeError, TypeError):
                        continue

                if isinstance(e, dict) and e.get("name"):
                    involved.append(e["name"])

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

    async def _get_upcoming_events(
        self, conn: Connection, current_cycle: int
    ) -> list[EventSummary]:
        """Get upcoming events via reader"""
        rows = await self.reader.get_upcoming_events_full(conn, current_cycle)

        result = []
        for r in rows:
            participants = r.get("participants") or []
            participants = [p for p in participants if p]

            result.append(
                EventSummary(
                    title=r["title"],
                    planned_cycle=r["planned_cycle"],
                    planned_time=r.get("time"),
                    location=r.get("location_name"),
                    participants=participants,
                    type=r["type"],
                )
            )

        return result

    # =========================================================================
    # FACTS
    # =========================================================================

    async def _get_important_facts(
        self, conn: Connection, current_cycle: int
    ) -> list[RecentFact]:
        """Get important recent facts via reader"""
        rows = await self.reader.get_important_facts(conn, current_cycle)
        return [self._row_to_recent_fact(r) for r in rows]

    async def _get_location_facts(
        self, conn: Connection, location_name: str, current_cycle: int
    ) -> list[RecentFact]:
        """Get facts related to a location via reader"""
        rows = await self.reader.get_location_facts(conn, location_name, current_cycle)
        return [self._row_to_recent_fact(r) for r in rows]

    async def _get_npc_facts(
        self, conn: Connection, npc_names: list[str], current_cycle: int
    ) -> list[RecentFact]:
        """Get facts involving specific NPCs via reader"""
        rows = await self.reader.get_npc_facts(conn, npc_names, current_cycle)
        return [self._row_to_recent_fact(r) for r in rows]

    def _row_to_recent_fact(self, r: dict) -> RecentFact:
        """Convert a row to RecentFact, handling JSON parsing"""
        participants_raw = parse_json_list(r.get("participants"))
        involves = []

        for p in participants_raw:
            if isinstance(p, dict) and p.get("name"):
                involves.append(p["name"])
            elif isinstance(p, str):
                try:
                    parsed = json.loads(p)
                    if isinstance(parsed, dict) and parsed.get("name"):
                        involves.append(parsed["name"])
                except (json.JSONDecodeError, TypeError):
                    pass

        return RecentFact(
            cycle=r["cycle"],
            description=r["description"][:200] if r.get("description") else "",
            importance=r.get("importance", 3),
            involves=involves,
        )

    # =========================================================================
    # HISTORY
    # =========================================================================

    async def _get_cycle_summaries(
        self, conn: Connection, current_cycle: int, limit: int = 7
    ) -> list[str]:
        """Get summaries of recent cycles via reader"""
        rows = await self.reader.get_cycle_summaries_range(conn, current_cycle, limit)

        return [
            f"Cycle {r['cycle']} ({r['date'] or f'Cycle {r['cycle']}'}) : {r['summary']}"
            for r in reversed(rows)
        ]

    async def _get_recent_messages(
        self, conn: Connection, limit: int = 5
    ) -> list[MessageSummary]:
        """Get summaries of recent messages via reader"""
        rows = await self.reader.get_recent_message_summaries(conn, limit)

        return [
            MessageSummary(
                role=r["role"],
                summary=r["summary"][:200] if r.get("summary") else "",
                cycle=r["cycle"],
            )
            for r in reversed(rows)
        ]

    # =========================================================================
    # UTILITIES
    # =========================================================================

    async def get_known_entity_names(self, conn: Connection) -> list[str]:
        """Get all known entity names via reader"""
        entities = await self.reader.get_entities(conn)
        return [e["name"] for e in entities]

    async def get_known_entity_display_names(self, conn: Connection) -> list[dict]:
        """Get entities with display names for narrator via reader"""
        rows = await self.reader.get_entities_with_display_names(conn)

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
