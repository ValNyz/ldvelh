"""
LDVELH - Organizations Extractor
Handles organization CRUD, ambient updates, and organization-related facts.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from prompts.extractions import organizations_prompt
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


class OrganizationsExtractor(BaseExtractor):
    extraction_type = "organizations"
    tool_name = "extract_organizations"
    tool_description = "Extract organization changes from narrative text"

    async def _build_context(self, conn: Connection, messages: list[dict]) -> dict:
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
        self, context: dict, narrative_texts: list[str], cycle: int
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
            narrative_texts=narrative_texts,
            cycle=cycle,
            known_organizations=known_orgs,
            active_arcs_with_orgs=context.get("arcs_with_orgs"),
        )
        return organizations_prompt.SYSTEM_PROMPT, user_prompt

    def _get_tool_schema(self) -> dict:
        return organizations_prompt.get_tool_schema()

    async def _populate(
        self, conn: Connection, raw_result: dict, cycle: int
    ) -> dict:
        stats = {"entities_created": 0, "entities_updated": 0,
                 "ambients_updated": 0, "facts_created": 0, "errors": []}

        for ec_data in raw_result.get("entities_created", []):
            try:
                ec_data.setdefault("entity_type", "organization")
                ec = EntityCreation.model_validate(ec_data)
                if ec.entity_type != EntityType.ORGANIZATION:
                    continue
                await self.populator._process_entity_creation(conn, ec, cycle)
                stats["entities_created"] += 1
            except Exception as e:
                stats["errors"].append(f"create: {e}")

        if stats["entities_created"]:
            await self.populator.load_registry(conn)

        for eu_data in raw_result.get("entities_updated", []):
            try:
                eu_data.setdefault("entity_type", "organization")
                eu = EntityUpdate.model_validate(eu_data)
                await self.populator._process_entity_update(conn, eu, cycle)
                stats["entities_updated"] += 1
            except Exception as e:
                stats["errors"].append(f"update: {e}")

        for amb_data in raw_result.get("ambient_updates", []):
            try:
                amb_data.setdefault("entity_type", "organization")
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
