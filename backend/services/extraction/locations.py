"""
LDVELH - Locations Extractor
Handles location CRUD, stub enrichment, ambient updates, and location-related facts.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from prompts.extraction import locations_prompt
from schema import EntityType, FactData
from schema.extraction import AmbientUpdate, EntityCreation, EntityUpdate

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

    async def _build_context(self, conn: Connection, messages: list[dict]) -> dict:
        locations = await self.reader.get_locations(conn)
        stub_locations = await self.reader.get_stub_locations(conn)
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
        self, context: dict, narrative_texts: list[str], cycle: int,
        resolution_map=None,
    ) -> tuple[str, str]:
        known_locs = [
            {
                "name": loc["name"],
                "sector": loc.get("sector"),
                "location_type": loc.get("location_type"),
                "ambient": loc.get("ambient"),
            }
            for loc in context["locations"]
        ]
        user_prompt = locations_prompt.build_user_prompt(
            narrative_texts=narrative_texts,
            cycle=cycle,
            known_locations=known_locs,
            stub_locations=context.get("stub_locations"),
            active_arcs_with_locations=context.get("arcs_with_locations"),
        )
        if resolution_map:
            from prompts.extraction.shared import RESOLUTION_SECTION_HEADER
            section = resolution_map.to_prompt_section("location")
            if section:
                user_prompt += f"\n\n{RESOLUTION_SECTION_HEADER}{section}"
        return locations_prompt.SYSTEM_PROMPT, user_prompt

    def _get_tool_schema(self) -> dict:
        return locations_prompt.get_tool_schema()

    async def _populate(
        self, conn: Connection, raw_result: dict, cycle: int
    ) -> dict:
        stats = {"entities_created": 0, "entities_updated": 0,
                 "ambients_updated": 0, "facts_created": 0, "errors": []}

        for ec_data in raw_result.get("entities_created", []):
            try:
                ec_data.setdefault("entity_type", "location")
                ec = EntityCreation.model_validate(ec_data)
                if ec.entity_type != EntityType.LOCATION:
                    continue
                await self.populator._process_entity_creation(conn, ec, cycle)
                stats["entities_created"] += 1
            except Exception as e:
                stats["errors"].append(f"create: {e}")

        if stats["entities_created"]:
            await self.populator.load_registry(conn)

        for eu_data in raw_result.get("entities_updated", []):
            try:
                eu_data.setdefault("entity_type", "location")
                eu = EntityUpdate.model_validate(eu_data)
                await self.populator._process_entity_update(conn, eu, cycle)
                stats["entities_updated"] += 1
            except Exception as e:
                stats["errors"].append(f"update: {e}")

        for amb_data in raw_result.get("ambient_updates", []):
            try:
                amb_data.setdefault("entity_type", "location")
                amb = AmbientUpdate.model_validate(amb_data)
                success = await self.populator.update_entity(
                    conn, amb.entity_type, amb.entity_ref, {"ambient": amb.ambient}
                )
                if success:
                    stats["ambients_updated"] += 1
            except Exception as e:
                stats["errors"].append(f"ambient: {e}")

        for fact_data in raw_result.get("facts", []):
            try:
                fact_data.setdefault("cycle", cycle)
                fact = FactData.model_validate(fact_data)
                if await self.populator.create_fact(conn, fact):
                    stats["facts_created"] += 1
            except Exception as e:
                stats["errors"].append(f"fact: {e}")

        return stats
