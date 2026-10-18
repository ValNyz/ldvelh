"""
LDVELH - Narrative Arcs Extractor
Handles arcs, relations (cross-entity), events, segment summary, and world-state facts.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from prompts.extraction import narrative_arcs_prompt
from schema import RelationType
from schema.extraction import (
    EventScheduledExtraction,
    RelationCreation,
    RelationEnd,
    RelationUpdate,
)

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


class NarrativeArcsExtractor(BaseExtractor):
    extraction_type = "narrative_arcs"
    tool_name = "extract_narrative_arcs"
    tool_description = "Extract arcs, relations, events, and summary from narrative text"

    async def _build_context(self, conn: Connection, narrator_deltas: dict) -> dict:
        entities = await self.reader.get_entities(conn)
        known_entities = [e["name"] for e in entities]

        active_arcs = await self.reader.get_active_arcs(conn)
        arcs_list = []
        for arc in active_arcs:
            participants = _parse_participant_names(arc.get("participants") or [])
            arcs_list.append({
                "title": arc["title"],
                "domain": arc.get("domain", "personal"),
                "intensity": arc.get("intensity", 3),
                "progress": arc.get("progress", 0),
                "involved": participants,
            })

        relations = await self.reader.get_relations(conn)
        known_relations = [
            {
                "source": r.get("source_name", ""),
                "target": r.get("target_name", ""),
                "type": r.get("relation_type", ""),
                "level": r.get("level"),
            }
            for r in relations[:30]
        ]

        return {
            "known_entities": known_entities,
            "active_arcs": arcs_list,
            "known_relations": known_relations,
        }

    def _build_prompts(
        self, context: dict, narrative_text: str, cycle: int,
        resolution_map=None,
    ) -> tuple[str, str]:
        user_prompt = narrative_arcs_prompt.build_user_prompt(
            narrative_text=narrative_text,
            cycle=cycle,
            known_entities=context["known_entities"],
            active_arcs=context.get("active_arcs") or None,
            known_relations=context.get("known_relations") or None,
        )
        if resolution_map:
            from prompts.extraction.shared import RESOLUTION_SECTION_HEADER
            # All entity types — arcs reference characters, locations, etc.
            section = resolution_map.to_prompt_section(None)
            if section:
                user_prompt += f"\n\n{RESOLUTION_SECTION_HEADER}{section}"
        return narrative_arcs_prompt.SYSTEM_PROMPT, user_prompt

    def _get_tool_schema(self) -> dict:
        return narrative_arcs_prompt.get_tool_schema()

    async def _populate(
        self, conn: Connection, raw_result: dict, cycle: int
    ) -> dict:
        stats = {"relations_created": 0, "relations_updated": 0, "relations_ended": 0,
                 "events_scheduled": 0, "facts_created": 0, "errors": []}
        items = [
            ("rel_create", "relations_created", self._create_relation, "relations_created"),
            ("rel_update", "relations_updated", self._update_relation, "relations_updated"),
            ("rel_end", "relations_ended", self._end_relation, "relations_ended"),
            ("event", "events_scheduled", self._schedule_event, "events_scheduled"),
        ]
        for label, key, write, counter in items:
            await self._write_items(conn, stats, label, raw_result.get(key),
                                    lambda d, write=write: write(conn, d, cycle), counter)
        await self._write_facts(conn, stats, raw_result, cycle)

        # Segment summary -> chronology
        summary = raw_result.get("segment_summary", "")
        if summary:
            await self._write_item(
                conn, stats, "chronology",
                lambda: self.populator.save_chronology_entry(conn, cycle=cycle, summary=summary),
            )
        return stats

    async def _create_relation(self, conn: Connection, rc_data: dict, cycle: int) -> bool:
        """Create a relation (skip OWNS, handled by inventory)."""
        rc_data.setdefault("cycle", cycle)
        rc = RelationCreation.model_validate(rc_data)
        if rc.relation.relation_type == RelationType.OWNS:
            return False
        return bool(await self.populator.create_relation(conn, rc.relation, rc.cycle))

    async def _update_relation(self, conn: Connection, ru_data: dict, cycle: int) -> bool:
        ru = RelationUpdate.model_validate(ru_data)
        updated = await conn.fetchval(
            """WITH upd AS (
                UPDATE relations SET
                    level = COALESCE($5, level),
                    context = COALESCE($6, context),
                    known_by_protagonist = COALESCE($7, known_by_protagonist)
                WHERE game_id = $1
                  AND source_id = find_entity($1, $2)
                  AND target_id = find_entity($1, $3)
                  AND type = $4::relation_type
                  AND end_cycle IS NULL
                RETURNING 1)
            SELECT COUNT(*) FROM upd""",
            self.game_id,
            ru.source_ref, ru.target_ref, ru.relation_type.value,
            ru.new_level, ru.new_context, ru.now_known,
        )
        if not updated:
            # Constant message: the refs are story text and must not reach stats["errors"].
            # Raising lets the per-item savepoint (#24) record the failure.
            raise LookupError("no active relation matched the update")
        return True

    async def _end_relation(self, conn: Connection, re_data: dict, cycle: int) -> bool:
        re = RelationEnd.model_validate(re_data)
        await self.populator.end_relation(
            conn, re.source_ref, re.target_ref, re.relation_type, re.cycle, re.reason,
        )
        return True

    async def _schedule_event(self, conn: Connection, ev_data: dict, cycle: int) -> bool:
        ev = EventScheduledExtraction.model_validate(ev_data)
        await self.populator._schedule_event(conn, ev)
        return True
