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
    Fact,
    MessageSummary,
    CycleSummary,
    PersonalAISummary,
    NPCLightSummary,
    OrganizationSummary,
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
        all_npcs = await self._build_all_npcs_light_summary(conn)

        # Organizations - AJOUTER
        organizations = await self._build_organizations(conn)

        # Commitments & Events
        commitments = await self._build_commitments(conn)
        events = await self._build_events(conn, current_cycle)

        # Facts
        facts = await self._build_facts(
            conn, current_cycle, current_location_name, npcs_present
        )

        # History
        cycle_summaries = await self._build_cycle_summaries(conn, current_cycle)
        (
            recent_messages,
            earlier_cycle_messages,
        ) = await self._build_conversation_context(conn, current_cycle, recent_limit=10)
        tone_notes = ""

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
            all_npcs=all_npcs,
            organizations=organizations,
            active_commitments=commitments,
            upcoming_events=events,
            facts=facts,
            cycle_summaries=cycle_summaries,
            recent_messages=recent_messages,
            earlier_cycle_messages=earlier_cycle_messages,
            player_input=player_input,
            world_name=world_info.get("name", "Station"),
            world_atmosphere=world_info.get("atmosphere", ""),
            tone_notes=tone_notes,
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
        # skills_str = [f"{s['name']} ({s['level']})" for s in row.get("skills", [])]

        return ProtagonistState(
            name=row["name"],
            credits=row.get("credits") or 0,
            energy=GaugeState(value=float(row.get("energy") or 3)),
            morale=GaugeState(value=float(row.get("morale") or 3)),
            health=GaugeState(value=float(row.get("health") or 4)),
            # skills=skills_str,
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
                name=name, type="Inconnu", sector="Inconnu", atmosphere="Inconnu"
            )
        return LocationSummary(
            name=row["name"],
            type=row.get("location_type") or "Inconnu",
            sector=row.get("sector") or "Inconnu",
            atmosphere=row.get("atmosphere") or "Inconnu",
            accessible=row.get("accessible", True),
        )

    async def _build_connected_locations(
        self, conn: Connection, current_location: str
    ) -> list[LocationSummary]:
        """Build connected locations list"""
        rows = await self.reader.get_sibling_locations(conn, current_location)
        return [
            LocationSummary(
                name=r["name"],
                type=r.get("location_type") or "Inconnu",
                sector=r.get("sector") or "Inconnu",
                atmosphere=r.get("atmosphere") or "Inconnu",
                accessible=True,
            )
            for r in rows
        ]

    # =========================================================================
    # NPCs
    # =========================================================================

    async def _build_all_npcs_light_summary(
        self, conn: Connection
    ) -> list[NPCLightSummary]:
        """Build light summary of ALL NPCs (known and unknown)"""
        rows = await self.reader.get_all_characters(conn)
        return [
            NPCLightSummary(
                name=r["name"]
                if r["known_by_protagonist"]
                else (r["unknown_name"] or "Inconnu(e)"),
                occupation=r.get("occupation"),
                species=r.get("species") or "human",
                relationship_level=r.get("relation_level"),
                usual_location=r.get("usual_location"),
                known=r["known_by_protagonist"],
            )
            for r in rows
        ]

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
    # ORGANIZATIONS
    # =========================================================================

    async def _build_organizations(self, conn: Connection) -> list[OrganizationSummary]:
        """Build organizations summary"""
        rows = await self.reader.get_known_organizations(conn)
        return [
            OrganizationSummary(
                name=r["name"],
                org_type=r.get("org_type"),
                domain=r.get("domain"),
                protagonist_relation=r.get("protagonist_relation"),
            )
            for r in rows
        ]

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
            description = (
                r["description"].split(":") if r.get("description") else ["", ""]
            )

            result.append(
                CommitmentSummary(
                    type=r["type"],
                    title=description[0],
                    description_brief=description[1][1:],
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
        current_location_name: str,
        npcs_present: list[NPCSummary],
    ) -> list[Fact]:
        """Build unified list of recent facts (deduplicated)"""
        seen_ids = set()
        result = []

        # 1. Important facts (importance >= 3)
        important = await self.reader.get_facts_with_participants(
            conn, cycle=current_cycle, min_importance=3, limit=10
        )
        for r in important:
            if r["id"] not in seen_ids:
                seen_ids.add(r["id"])
                result.append(self._row_to_recent_fact(r))

        # 2. Location facts (si pas déjà inclus)
        location_facts = await self.reader.get_facts_with_participants(
            conn, cycle=current_cycle, location_name=current_location_name, limit=5
        )
        for r in location_facts:
            if r["id"] not in seen_ids:
                seen_ids.add(r["id"])
                result.append(self._row_to_recent_fact(r))

        # 3. NPC facts (si pas déjà inclus)
        if npcs_present:
            npc_names = [n.name for n in npcs_present]
            npc_facts = await self.reader.get_facts_with_participants(
                conn, cycle=current_cycle, npc_names=npc_names, limit=5
            )
            for r in npc_facts:
                if r["id"] not in seen_ids:
                    seen_ids.add(r["id"])
                    result.append(self._row_to_recent_fact(r))

        # Trier par importance décroissante puis cycle décroissant
        result.sort(key=lambda f: (-f.importance, -f.cycle))
        return result[:15]

    def _row_to_recent_fact(self, r: dict) -> Fact:
        """Convert row to Fact"""
        participants = r.get("participants") or []
        involves = [
            p["name"] for p in participants if isinstance(p, dict) and p.get("name")
        ]

        return Fact(
            cycle=r["cycle"],
            description=r["description"] if r.get("description") else "",
            importance=r.get("importance", 1),
            involves=involves,
        )

    # =========================================================================
    # HISTORY
    # =========================================================================

    async def _build_cycle_summaries(
        self, conn: Connection, current_cycle: int, limit: int = 15
    ) -> list[str]:
        """Build cycle summaries"""
        rows = await self.reader.get_cycle_summaries(
            conn, max_cycle=current_cycle, limit=limit
        )
        return [
            CycleSummary(cycle=r["cycle"], date=r["date"], summary=r["summary"])
            for r in rows
        ]

    async def _build_conversation_context(
        self, conn: Connection, current_cycle: int, recent_limit: int = 10
    ) -> tuple[list[MessageSummary], list[MessageSummary]]:
        """
        Build conversation context:
        - recent_messages: les 10 derniers messages (détaillés)
        - earlier_cycle_messages: résumés des messages plus anciens du cycle en cours

        Returns: (recent_messages, earlier_cycle_messages)
        """
        # 1. Les N derniers messages (tous cycles confondus)
        recent_rows = await self.reader.get_messages(conn, recent_limit)
        recent_messages = [
            MessageSummary(
                role=r["role"],
                summary=r.get("content", ""),
                cycle=r["cycle"],
                time=r.get("time"),
            )
            for r in recent_rows
        ]

        # 2. IDs des messages récents pour les exclure
        recent_ids = {r.get("id") for r in recent_rows if r.get("id")}

        # 3. Tous les autres messages du cycle en cours (résumés courts)
        cycle_rows = await self.reader.get_cycle_messages(conn, current_cycle)
        earlier_cycle_messages = [
            MessageSummary(
                role=r["role"],
                summary=r.get("summary", ""),
                cycle=r["cycle"],
                time=r.get("time"),
            )
            for r in cycle_rows
            if r.get("id") not in recent_ids
        ]

        return recent_messages, earlier_cycle_messages
