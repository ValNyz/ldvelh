"""
LDVELH - Locations Extractor
Handles location CRUD, stub enrichment, ambient updates, and location-related facts.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from prompts.extraction import locations_prompt
from prompts.extraction.shared import handled
from schema import EntityType

from .base import BaseExtractor

if TYPE_CHECKING:
    from asyncpg import Connection

logger = logging.getLogger(__name__)


def _parse_participant_names(raw: list) -> list[str]:
    names = []
    for p in raw:
        if isinstance(p, dict):
            name = p.get("name", "")
        elif isinstance(p, str):
            try:
                parsed = json.loads(p)
                name = parsed.get("name", p) if isinstance(parsed, dict) else p
            except (json.JSONDecodeError, TypeError):
                name = p
        else:
            continue
        if name:
            names.append(name)
    return names


class LocationsExtractor(BaseExtractor):
    extraction_type = "locations"
    tool_name = "extract_locations"
    tool_description = "Extract location changes from narrative text"

    async def _build_context(self, conn: Connection, narrator_deltas: dict) -> dict:
        locations = await self._with_handles(conn, await self.reader.get_locations(conn))
        handle_of = {loc["name"]: loc.get("handle") for loc in locations}
        stub_locations = [
            handled(name, handle_of.get(name))
            for name in await self.reader.get_stub_locations(conn)
        ]
        active_arcs = await self.reader.get_active_arcs(conn)

        arcs_with_locs = []
        for arc in active_arcs:
            participants = _parse_participant_names(arc.get("participants") or [])
            arcs_with_locs.append({
                "title": arc["title"],
                "domain": arc.get("domain", "personal"),
                "intensity": arc.get("intensity", 3),
                "participants": participants,
            })

        return {
            "locations": locations,
            "stub_locations": stub_locations,
            "arcs_with_locations": arcs_with_locs,
        }

    def _build_prompts(
        self, context: dict, narrative_text: str, cycle: int
    ) -> tuple[str, str]:
        known_locs = [
            {
                "name": loc["name"],
                "handle": loc.get("handle"),
                "sector": loc.get("sector"),
                "location_type": loc.get("location_type"),
                "ambient": loc.get("ambient"),
            }
            for loc in context["locations"]
        ]
        user_prompt = locations_prompt.build_user_prompt(
            narrative_text=narrative_text,
            cycle=cycle,
            known_locations=known_locs,
            stub_locations=context.get("stub_locations"),
            active_arcs_with_locations=context.get("arcs_with_locations"),
        )
        return locations_prompt.SYSTEM_PROMPT, user_prompt

    def _get_tool_schema(self) -> dict:
        return locations_prompt.get_tool_schema()

    async def _populate(
        self, conn: Connection, raw_result: dict, cycle: int
    ) -> dict:
        stats = {"entities_created": 0, "entities_updated": 0,
                 "ambients_updated": 0, "facts_created": 0, "errors": []}
        await self._write_entities(conn, stats, raw_result, cycle, EntityType.LOCATION)
        await self._write_facts(conn, stats, raw_result, cycle)
        return stats
