"""
LDVELH - Context Builder Service
Builds narration context from database using KnowledgeGraphReader
"""

from __future__ import annotations
import json
from uuid import UUID
from typing import TYPE_CHECKING

from schema.narration import (
    NarrationContext,
    ProtagonistState,
    InventoryItem,
    LocationSummary,
    NPCSummary,
    ArcSummary,
    ActiveArcSummary,
    CompanionSummary,
    EventSummary,
    Fact,
    CycleSummary,
    NPCLightSummary,
    OrganizationSummary,
)
from schema import ArcDomain

from kg.reader import KnowledgeGraphReader
from services.engine import get_engine

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

        # Game state (date, world metadata)
        game = await self.reader.get_game(conn) or {}

        # Genre info
        genre = await self.reader.get_genre(conn, game.get("genre_id"))

        # Engine info
        engine_type = game.get("engine", "none")
        engine = get_engine(engine_type)
        engine_stats = None
        if engine_type != "none":
            engine_stats = await engine.get_stats(conn, self.game_id)

        # Protagonist
        protagonist = await self._build_protagonist_state(conn)

        # Inventory
        inventory = await self._build_inventory(conn)

        # Companion
        companion = await self._build_companion(conn)
        self._companion_name = companion.name.lower() if companion else None

        # Locations
        current_location = await self._build_current_location(
            conn, current_location_name
        )
        connected_locations = await self._build_connected_locations(
            conn, current_location_name
        )

        # NPCs — fetch all once, derive subsets
        all_characters = await self.reader.get_all_characters(conn)
        all_npcs = self._build_all_npcs_light(all_characters)

        npcs_present = await self._build_npcs_at_location(conn, current_location_name)
        present_names = {n.name for n in npcs_present}
        npcs_relevant = self._build_relevant_npcs(all_characters, present_names)

        # Load arcs once (used for NPCs and active arcs)
        arcs_rows = await self.reader.get_active_arcs(conn)

        # Enrich NPCs with arcs
        self._enrich_npcs_with_arcs(npcs_present, arcs_rows)
        self._enrich_npcs_with_arcs(npcs_relevant, arcs_rows)

        # Organizations
        organizations = await self._build_organizations(conn, protagonist)

        # Arcs & Events
        active_arcs_list = self._build_active_arcs(arcs_rows)
        events = await self._build_events(conn, current_cycle)

        # Facts
        facts = await self._build_facts(conn, current_cycle)

        # Active narrative seeds
        active_seeds = await self.reader.get_active_seeds(conn)

        # Requested entity details (from narrator info_requests at previous turn)
        requested_entity_details = await self._build_requested_details(conn)

        # Cycle summaries — only for cycles BEFORE the conversation window
        # (last 2 cycles are in the API messages array as multi-turn history)
        history_window_start = max(1, current_cycle - 1)
        cycle_summaries = await self._build_cycle_summaries(
            conn, current_cycle=history_window_start - 1
        )
        tone_notes = ""

        # Director plan (latest)
        director_guidance, director_tension, director_events = await self._load_director_plan(conn)

        return NarrationContext(
            current_cycle=current_cycle,
            current_time=current_time,
            current_date=game.get("current_date") or "Jour 1",
            current_location=current_location,
            connected_locations=connected_locations,
            protagonist=protagonist,
            inventory=inventory,
            companion=companion,
            npcs_present=npcs_present,
            npcs_relevant=npcs_relevant,
            all_npcs=all_npcs,
            organizations=organizations,
            active_arcs=active_arcs_list,
            upcoming_events=events,
            facts=facts,
            active_seeds=active_seeds,
            requested_entity_details=requested_entity_details,
            cycle_summaries=cycle_summaries,
            player_input=player_input,
            world_name=game.get("world_name") or world_info.get("name", "Station"),
            world_description=game.get("world_description") or "",
            world_atmosphere=game.get("world_atmosphere") or world_info.get("atmosphere", ""),
            tone_notes=tone_notes,
            director_guidance=director_guidance,
            director_tension=director_tension,
            director_planned_events=director_events,
            engine_type=engine_type,
            engine_stats=engine_stats,
            genre=genre,
        )

    # =========================================================================
    # DIRECTOR
    # =========================================================================

    async def _load_director_plan(self, conn) -> tuple[str | None, int | None, list]:
        """Load the most recent Director plan for this game."""
        row = await conn.fetchrow(
            """SELECT narrator_guidance, tension_level, planned_events
               FROM director_plans
               WHERE game_id = $1
               ORDER BY created_at DESC LIMIT 1""",
            self.game_id,
        )
        if not row:
            return None, None, []
        raw_events = row["planned_events"]
        if not raw_events:
            events = []
        elif isinstance(raw_events, str):
            import json
            events = json.loads(raw_events)
        else:
            events = raw_events
        return row["narrator_guidance"], row["tension_level"], events

    # =========================================================================
    # PROTAGONIST
    # =========================================================================

    async def _build_protagonist_state(self, conn: Connection) -> ProtagonistState:
        """Build protagonist state from reader"""
        row = await self.reader.get_protagonist(conn)
        if not row:
            raise ValueError("Protagonist not found")

        hobbies = row.get("hobbies") or []

        return ProtagonistState(
            name=row["name"],
            credits=row.get("credits") or 0,
            hobbies=hobbies,
            current_occupation=row.get("occupation"),
            employer=row.get("employer_name"),
            gender=row.get("gender"),
            description=row.get("description"),
            backstory=row.get("backstory"),
            origin=row.get("origin"),
        )

    async def _build_inventory(self, conn: Connection) -> list[InventoryItem]:
        """Build inventory from v_protagonist_inventory view"""
        rows = await self.reader.get_inventory(conn)
        return [
            InventoryItem(
                name=r["object_name"],
                category=r.get("category") or "misc",
                quantity=r.get("quantity") or 1,
            )
            for r in rows
        ]

    async def _build_companion(
        self, conn: Connection
    ) -> CompanionSummary | None:
        """Build companion from companions table"""
        row = await self.reader.get_companion(conn)
        if not row:
            return None

        traits = row.get("traits") or []
        return CompanionSummary(
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
        row = await self.reader.get_location_by_name(conn, name)
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
            ambient=row.get("ambient"),
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
                ambient=r.get("ambient"),
            )
            for r in rows
        ]

    # =========================================================================
    # NPCs
    # =========================================================================

    def _build_all_npcs_light(
        self, all_characters: list[dict]
    ) -> list[NPCLightSummary]:
        """Build light summary of ALL NPCs from pre-fetched data"""
        companion = getattr(self, "_companion_name", None)
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
                ambient=r.get("ambient"),
            )
            for r in all_characters
            if not companion or r["name"].lower() != companion
        ]

    async def _build_npcs_at_location(
        self, conn: Connection, location_name: str
    ) -> list[NPCSummary]:
        """Build NPCs at location"""
        rows = await self.reader.get_npcs_at_location(conn, location_name)
        companion = getattr(self, "_companion_name", None)
        return [
            self._row_to_npc_summary(r) for r in rows
            if not companion or r["name"].lower() != companion
        ]

    def _build_relevant_npcs(
        self, all_characters: list[dict], exclude_names: set[str]
    ) -> list[NPCSummary]:
        """Build relevant NPCs (highest relationship, not at current location)"""
        # all_characters is already sorted by relation_level DESC
        companion = getattr(self, "_companion_name", None)
        result = []
        for r in all_characters:
            if len(result) >= 5:
                break
            if companion and r["name"].lower() == companion:
                continue
            display_name = r["name"]
            if not r.get("known_by_protagonist", True):
                display_name = r.get("unknown_name") or "Inconnu(e)"
            if display_name in exclude_names:
                continue
            # Only include NPCs with an established relation
            if r.get("relation_level") is not None:
                result.append(self._row_to_npc_summary(r))
        return result

    def _row_to_npc_summary(self, row: dict) -> NPCSummary:
        """Convert DB row to NPCSummary"""
        display_name = row["name"]
        if not row.get("known_by_protagonist", True):
            display_name = row.get("unknown_name") or "Inconnu(e)"

        traits = row.get("traits") or []
        if isinstance(traits, str):
            import json
            try:
                traits = json.loads(traits)
            except (json.JSONDecodeError, TypeError):
                traits = []

        return NPCSummary(
            name=display_name,
            occupation=row.get("occupation") or "inconnu",
            species=row.get("species") or "human",
            traits=traits[:3],
            relationship_to_protagonist=row.get("relation_context", "")[:50]
            if row.get("relation_context")
            else None,
            relationship_level=row.get("relation_level"),
            usual_location=row.get("usual_location"),
            known=row.get("known_by_protagonist", True),
            active_arcs=[],  # Enriched later via _enrich_npcs_with_arcs
            ambient=row.get("ambient"),
        )

    def _enrich_npcs_with_arcs(
        self, npcs: list[NPCSummary], arcs_rows: list[dict]
    ) -> None:
        """Add arc summaries to NPCs based on arc participants."""
        # Build lookup: NPC name → list of arcs they participate in
        npc_arcs: dict[str, list[ArcSummary]] = {}
        for arc in arcs_rows:
            names = self._extract_participant_names(arc.get("participants") or [])
            for name in names:
                npc_arcs.setdefault(name.lower(), []).append(arc)

        for npc in npcs:
            npc_name = npc.name.lower()
            arcs = npc_arcs.get(npc_name, [])
            npc.active_arcs = [
                ArcSummary(
                    domain=ArcDomain(a.get("domain", "personal")),
                    title=a.get("title", ""),
                    situation_brief=(a.get("description") or "")[:100],
                    intensity=a.get("intensity", 3),
                )
                for a in arcs[:2]
            ]

    # =========================================================================
    # ORGANIZATIONS
    # =========================================================================

    async def _build_organizations(
        self, conn: Connection, protagonist: ProtagonistState
    ) -> list[OrganizationSummary]:
        """Build organizations summary with protagonist relation"""
        rows = await self.reader.get_organizations(conn)
        employer = (protagonist.employer or "").lower()
        return [
            OrganizationSummary(
                name=r["name"],
                org_type=r.get("org_type"),
                domain=r.get("domain"),
                protagonist_relation="employed_by"
                if r["name"].lower() == employer
                else None,
                ambient=r.get("ambient"),
            )
            for r in rows
        ]

    # =========================================================================
    # ARCS & EVENTS
    # =========================================================================

    @staticmethod
    def _extract_participant_names(participants: list) -> list[str]:
        """Extract human-readable names from participant entries.

        Handles both parsed dicts and JSON strings (asyncpg codec varies).
        """
        names = []
        for p in participants:
            if isinstance(p, dict):
                name = p.get("name")
            elif isinstance(p, str):
                # asyncpg may return jsonb elements as strings
                try:
                    obj = json.loads(p)
                    name = obj.get("name") if isinstance(obj, dict) else p
                except (json.JSONDecodeError, TypeError):
                    name = p
            else:
                name = None
            if name:
                names.append(name)
        return names

    def _build_active_arcs(self, arcs_rows: list[dict]) -> list[ActiveArcSummary]:
        """Build active arcs from narrative_arcs table (simplified — Director manages lifecycle)"""
        result = []
        for arc in arcs_rows:
            involved = self._extract_participant_names(arc.get("participants") or [])

            result.append(
                ActiveArcSummary(
                    type=arc.get("domain") or "personal",
                    title=arc.get("title", ""),
                    description_brief=(arc.get("description") or "")[:150],
                    involved=involved,
                    owner=arc.get("owner_name"),
                    owner_type=arc.get("owner_type"),
                )
            )
        return result

    async def _build_events(
        self, conn: Connection, current_cycle: int
    ) -> list[EventSummary]:
        """Build events from v_upcoming_events view"""
        rows = await self.reader.get_upcoming_events(conn, current_cycle)
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
    ) -> list[Fact]:
        """Build unified list of recent important facts"""
        rows = await self.reader.get_facts(
            conn, cycle=current_cycle, min_importance=3, limit=15
        )

        result = []
        for r in rows:
            involves = self._extract_participant_names(r.get("participants") or [])

            result.append(
                Fact(
                    cycle=r["cycle"],
                    description=r.get("description") or "",
                    importance=r.get("importance", 1),
                    involves=involves,
                )
            )

        return result

    # =========================================================================
    # REQUESTED ENTITY DETAILS
    # =========================================================================

    async def _build_requested_details(self, conn: "Connection") -> dict[str, dict]:
        """Load detailed info for entities requested by narrator at previous turn"""
        detail_requests = await self.reader.get_detail_requests(conn)
        if not detail_requests:
            return {}

        result = {}
        for name in detail_requests:
            details = await self.reader.get_entity_details_by_name(conn, name)
            if details:
                result[name] = details
        return result

    # =========================================================================
    # HISTORY
    # =========================================================================

    async def _build_cycle_summaries(
        self, conn: Connection, current_cycle: int, limit: int = 15
    ) -> list[CycleSummary]:
        """Build cycle summaries from chronology"""
        rows = await self.reader.get_chronology(
            conn, max_cycle=current_cycle, limit=limit
        )
        return [
            CycleSummary(
                cycle=r["cycle"],
                date=None,
                summary=r["summary"],
            )
            for r in rows
        ]

