"""
LDVELH - Characters Extractor
Handles character CRUD, ambient updates, skills, and character-related facts.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from kg import refs
from prompts.extraction import characters_prompt
from schema import EntityType
from schema.extraction import ProposedEntity

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

        # Get companion name to exclude from character extraction
        companion = await self.reader.get_companion(conn)
        self._companion_name = companion["name"].lower() if companion else None

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
            "companion_name": self._companion_name,
        }

    def _build_prompts(
        self, context: dict, narrative_text: str, cycle: int
    ) -> tuple[str, str]:
        known_chars = [
            {
                "name": c["name"],
                # A character known only by its descriptor is named by it already.
                "descriptor": c.get("descriptor") if c.get("descriptor") != c["name"] else None,
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
        return characters_prompt.SYSTEM_PROMPT, user_prompt

    def _get_tool_schema(self) -> dict:
        return characters_prompt.get_tool_schema()

    async def _populate(
        self, conn: Connection, raw_result: dict, cycle: int
    ) -> dict:
        stats = {"entities_created": 0, "entities_updated": 0, "ambients_updated": 0,
                 "facts_created": 0, "errors": []}
        await self._write_entities(conn, stats, raw_result, cycle, EntityType.CHARACTER)
        await self._write_items(conn, stats, "remove", raw_result.get("entities_removed"),
                                lambda d: self._remove(conn, d, cycle))
        await self._write_items(conn, stats, "skill", raw_result.get("skills_changed"),
                                lambda d: self._skill(conn, d, cycle))
        await self._write_facts(conn, stats, raw_result, cycle)
        return stats

    def _skip_proposal(self, proposed: ProposedEntity) -> bool:
        """Skip the companion's name to avoid duplication."""
        companion_name = getattr(self, '_companion_name', None)
        if companion_name and proposed.label.lower() == companion_name:
            logger.info("[CHARACTERS] Skipping the companion (already in companions table)")
            return True
        return False

    async def _remove(self, conn: Connection, er_data: dict, cycle: int) -> None:
        """The removed character, by the id its reference resolves to, live first
        (RefUnresolved: counted by the item's savepoint); one already removed is a counted
        no-op."""
        identity = await self.populator.identity(conn)
        entity_id = await refs.required(
            identity, conn, er_data.get("entity_ref", ""), EntityType.CHARACTER.value,
            live_first=True)
        await self.populator.remove_extracted_entity(
            conn, entity_id, EntityType.CHARACTER, er_data.get("cycle", cycle),
        )

    async def _skill(self, conn: Connection, skill_data: dict, cycle: int) -> None:
        from schema import Skill
        skill = Skill.model_validate(skill_data)
        proto_id = await self.populator.protagonist_id(conn)
        if proto_id:
            await self.populator.update_skill(conn, skill, cycle, protagonist_id=proto_id)
