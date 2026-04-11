"""
LDVELH - Characters Extractor
Handles character CRUD, ambient updates, skills, and character-related facts.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from prompts.extraction import characters_prompt
from schema import EntityType, FactData
from schema.extraction import AmbientUpdate, CharactersExtraction, EntityCreation, EntityUpdate

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


class CharactersExtractor(BaseExtractor):
    extraction_type = "characters"
    tool_name = "extract_characters"
    tool_description = "Extract character changes from narrative text"

    async def _build_context(self, conn: Connection, narrator_deltas: dict) -> dict:
        characters = await self.reader.get_all_characters(conn)
        active_arcs = await self.reader.get_active_arcs(conn)

        # Filter arcs that involve characters
        arcs_with_chars = []
        for arc in active_arcs:
            participants = _parse_participant_names(arc.get("participants") or [])
            arcs_with_chars.append({
                "title": arc["title"],
                "domain": arc.get("domain", "personal"),
                "intensity": arc.get("intensity", 3),
                "participants": participants,
            })

        return {
            "characters": characters,
            "arcs_with_characters": arcs_with_chars,
        }

    def _build_prompts(
        self, context: dict, narrative_text: str, cycle: int,
        resolution_map=None,
    ) -> tuple[str, str]:
        known_chars = [
            {
                "name": c["name"],
                "occupation": c.get("occupation"),
                "known_by_protagonist": c.get("known_by_protagonist", True),
                "mood": c.get("mood"),
                "ambient": c.get("ambient"),
            }
            for c in context["characters"]
        ]
        user_prompt = characters_prompt.build_user_prompt(
            narrative_text=narrative_text,
            cycle=cycle,
            known_characters=known_chars,
            active_arcs_with_characters=context.get("arcs_with_characters"),
        )
        if resolution_map:
            from prompts.extraction.shared import RESOLUTION_SECTION_HEADER
            section = resolution_map.to_prompt_section("character")
            if section:
                user_prompt += f"\n\n{RESOLUTION_SECTION_HEADER}{section}"
        return characters_prompt.SYSTEM_PROMPT, user_prompt

    def _get_tool_schema(self) -> dict:
        return characters_prompt.get_tool_schema()

    async def _populate(
        self, conn: Connection, raw_result: dict, cycle: int
    ) -> dict:
        stats = {"entities_created": 0, "entities_updated": 0, "ambients_updated": 0,
                 "facts_created": 0, "errors": []}

        # Entities created
        for ec_data in raw_result.get("entities_created", []):
            try:
                ec_data.setdefault("entity_type", "character")
                ec = EntityCreation.model_validate(ec_data)
                if ec.entity_type != EntityType.CHARACTER:
                    continue
                await self.populator._process_entity_creation(conn, ec, cycle)
                stats["entities_created"] += 1
            except Exception as e:
                stats["errors"].append(f"create: {e}")

        # Reload registry after new entities
        if stats["entities_created"]:
            await self.populator.load_registry(conn)

        # Entities updated
        for eu_data in raw_result.get("entities_updated", []):
            try:
                eu_data.setdefault("entity_type", "character")
                eu = EntityUpdate.model_validate(eu_data)
                await self.populator._process_entity_update(conn, eu, cycle)
                stats["entities_updated"] += 1
            except Exception as e:
                stats["errors"].append(f"update: {e}")

        # Entities removed
        for er_data in raw_result.get("entities_removed", []):
            try:
                ref = er_data.get("entity_ref", "")
                reason_cycle = er_data.get("cycle", cycle)
                await self.populator.remove_entity(
                    conn, ref, EntityType.CHARACTER, reason_cycle
                )
            except Exception as e:
                stats["errors"].append(f"remove: {e}")

        # Ambient updates
        for amb_data in raw_result.get("ambient_updates", []):
            try:
                amb_data.setdefault("entity_type", "character")
                amb = AmbientUpdate.model_validate(amb_data)
                success = await self.populator.update_entity(
                    conn, amb.entity_type, amb.entity_ref, {"ambient": amb.ambient}
                )
                if success:
                    stats["ambients_updated"] += 1
            except Exception as e:
                stats["errors"].append(f"ambient: {e}")

        # Skills
        for skill_data in raw_result.get("skills_changed", []):
            try:
                from schema import Skill
                skill = Skill.model_validate(skill_data)
                proto_id = await self.populator._resolve_protagonist_id(conn)
                if proto_id:
                    await self.populator.update_skill(
                        conn, skill, cycle, protagonist_id=proto_id
                    )
            except Exception as e:
                stats["errors"].append(f"skill: {e}")

        # Facts
        for fact_data in raw_result.get("facts", []):
            try:
                fact_data.setdefault("cycle", cycle)
                fact = FactData.model_validate(fact_data)
                if await self.populator.create_fact(conn, fact):
                    stats["facts_created"] += 1
            except Exception as e:
                stats["errors"].append(f"fact: {e}")

        return stats
