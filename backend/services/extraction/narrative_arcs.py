"""
LDVELH - Narrative Arcs Extractor
Handles arcs, relations (cross-entity), events, segment summary, and world-state facts.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from kg import refs
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
        self, context: dict, narrative_text: str, cycle: int
    ) -> tuple[str, str]:
        user_prompt = narrative_arcs_prompt.build_user_prompt(
            narrative_text=narrative_text,
            cycle=cycle,
            known_entities=context["known_entities"],
            active_arcs=context.get("active_arcs") or None,
            known_relations=context.get("known_relations") or None,
        )
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
            ("event", "events_scheduled",
             lambda c, d, cy: self._schedule_event(c, stats, d, cy), "events_scheduled"),
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

    async def _ends(self, conn: Connection, source_ref: str, target_ref: str):
        """(source id, target id) of a relation: both must resolve (RefUnresolved
        otherwise, counted by the item's savepoint as `ref_dropped`)."""
        identity = await self.populator.identity(conn)
        return (await refs.required(identity, conn, source_ref),
                await refs.required(identity, conn, target_ref))

    async def _create_relation(self, conn: Connection, rc_data: dict, cycle: int) -> bool:
        """Create a relation (skip OWNS, handled by inventory)."""
        rc_data.setdefault("cycle", cycle)
        rc = RelationCreation.model_validate(rc_data)
        relation = rc.relation
        if relation.relation_type == RelationType.OWNS:
            return False
        source_id, target_id = await self._ends(conn, relation.source_ref,
                                                relation.target_ref)
        return bool(await self.populator.create_relation(
            conn, source_id, target_id, relation.relation_type, rc.cycle,
            level=relation.level, context=relation.context,
            known_by_protagonist=relation.known_by_protagonist,
        ))

    async def _update_relation(self, conn: Connection, ru_data: dict, cycle: int) -> bool:
        ru = RelationUpdate.model_validate(ru_data)
        source_id, target_id = await self._ends(conn, ru.source_ref, ru.target_ref)
        updated = await conn.fetchval(
            """WITH upd AS (
                UPDATE relations SET
                    level = COALESCE($5, level),
                    context = COALESCE($6, context),
                    known_by_protagonist = COALESCE($7, known_by_protagonist)
                WHERE game_id = $1
                  AND source_id = $2
                  AND target_id = $3
                  AND type = $4::relation_type
                  AND end_cycle IS NULL
                RETURNING 1)
            SELECT COUNT(*) FROM upd""",
            self.game_id,
            source_id, target_id, ru.relation_type.value,
            ru.new_level, ru.new_context, ru.now_known,
        )
        if not updated:
            # Constant message: the refs are story text and must not reach stats["errors"].
            # Raising lets the per-item savepoint (#24) record the failure.
            raise LookupError("no active relation matched the update")
        return True

    async def _end_relation(self, conn: Connection, re_data: dict, cycle: int) -> bool:
        re = RelationEnd.model_validate(re_data)
        source_id, target_id = await self._ends(conn, re.source_ref, re.target_ref)
        await self.populator.end_relation(
            conn, source_id, target_id, re.relation_type, re.cycle, re.reason,
        )
        return True

    async def _schedule_event(
        self, conn: Connection, stats: dict, ev_data: dict, cycle: int
    ) -> bool:
        ev = EventScheduledExtraction.model_validate(ev_data)
        await self.populator.schedule_event(conn, stats["errors"], ev)
        return True
