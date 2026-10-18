"""
LDVELH - Organizations Extractor
Handles organization CRUD, ambient updates, and organization-related facts.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from prompts.extraction import organizations_prompt
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


class OrganizationsExtractor(BaseExtractor):
    extraction_type = "organizations"
    tool_name = "extract_organizations"
    tool_description = "Extract organization changes from narrative text"

    async def _build_context(self, conn: Connection, narrator_deltas: dict) -> dict:
        organizations = await self.reader.get_organizations(conn)
        active_arcs = await self.reader.get_active_arcs(conn)

        arcs_with_orgs = []
        for arc in active_arcs:
            participants = _parse_participant_names(arc.get("participants") or [])
            arcs_with_orgs.append({
                "title": arc["title"],
                "domain": arc.get("domain", "personal"),
                "intensity": arc.get("intensity", 3),
                "participants": participants,
            })

        return {
            "organizations": organizations,
            "arcs_with_orgs": arcs_with_orgs,
        }

    def _build_prompts(
        self, context: dict, narrative_text: str, cycle: int,
        resolution_map=None,
    ) -> tuple[str, str]:
        known_orgs = [
            {
                "name": org["name"],
                "org_type": org.get("org_type"),
                "domain": org.get("domain"),
                "ambient": org.get("ambient"),
            }
            for org in context["organizations"]
        ]
        user_prompt = organizations_prompt.build_user_prompt(
            narrative_text=narrative_text,
            cycle=cycle,
            known_organizations=known_orgs,
            active_arcs_with_orgs=context.get("arcs_with_orgs"),
        )
        if resolution_map:
            from prompts.extraction.shared import RESOLUTION_SECTION_HEADER
            section = resolution_map.to_prompt_section("organization")
            if section:
                user_prompt += f"\n\n{RESOLUTION_SECTION_HEADER}{section}"
        return organizations_prompt.SYSTEM_PROMPT, user_prompt

    def _get_tool_schema(self) -> dict:
        return organizations_prompt.get_tool_schema()

    async def _populate(
        self, conn: Connection, raw_result: dict, cycle: int
    ) -> dict:
        stats = {"entities_created": 0, "entities_updated": 0,
                 "ambients_updated": 0, "facts_created": 0, "errors": []}
        await self._write_entities(conn, stats, raw_result, cycle, EntityType.ORGANIZATION)
        await self._write_facts(conn, stats, raw_result, cycle)
        return stats
