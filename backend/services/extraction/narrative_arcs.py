"""
LDVELH - Narrative Arcs Extractor
Handles arcs, relations (cross-entity), events, segment summary, and world-state facts.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from prompts.extractions import narrative_arcs_prompt
from schema import FactData, NarrativeArcData, RelationType
from schema.extraction import (
    ArcCreation,
    ArcResolutionExtraction,
    ArcUpdate,
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

    async def _build_context(self, conn: Connection, messages: list[dict]) -> dict:
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
        self, context: dict, narrative_texts: list[str], cycle: int
    ) -> tuple[str, str]:
        user_prompt = narrative_arcs_prompt.build_user_prompt(
            narrative_texts=narrative_texts,
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
        stats = {"arcs_created": 0, "arcs_updated": 0, "arcs_resolved": 0,
                 "relations_created": 0, "relations_updated": 0, "relations_ended": 0,
                 "events_scheduled": 0, "facts_created": 0, "errors": []}

        # Arcs created
        for arc_data in raw_result.get("arcs_created", []):
            try:
                arc = ArcCreation.model_validate(arc_data)
                arc_db = NarrativeArcData(
                    title=arc.title,
                    domain=arc.domain,
                    description=arc.description,
                    involved_entities=arc.involved_entities,
                    potential_triggers=arc.potential_triggers,
                    stakes=arc.stakes,
                    deadline_cycle=arc.deadline_cycle,
                    intensity=arc.intensity,
                )
                await self.populator.create_narrative_arc(conn, arc_db)
                stats["arcs_created"] += 1
            except Exception as e:
                stats["errors"].append(f"arc_create: {e}")

        # Arcs updated
        for au_data in raw_result.get("arcs_updated", []):
            try:
                au = ArcUpdate.model_validate(au_data)
                updated = await self.populator.update_arc(
                    conn,
                    arc_title=au.arc_title,
                    intensity=au.intensity,
                    progress=au.progress,
                    situation=au.situation,
                )
                if updated:
                    stats["arcs_updated"] += 1
            except Exception as e:
                stats["errors"].append(f"arc_update: {e}")

        # Arcs resolved
        for ar_data in raw_result.get("arcs_resolved", []):
            try:
                ar = ArcResolutionExtraction.model_validate(ar_data)
                await self.populator.resolve_arc(
                    conn, ar.arc_title, ar.resolution, cycle
                )
                stats["arcs_resolved"] += 1
            except Exception as e:
                stats["errors"].append(f"arc_resolve: {e}")

        # Relations created (skip OWNS)
        for rc_data in raw_result.get("relations_created", []):
            try:
                rc_data.setdefault("cycle", cycle)
                rc = RelationCreation.model_validate(rc_data)
                if rc.relation.relation_type == RelationType.OWNS:
                    continue
                result = await self.populator.create_relation(
                    conn, rc.relation, rc.cycle
                )
                if result:
                    stats["relations_created"] += 1
            except Exception as e:
                stats["errors"].append(f"rel_create: {e}")

        # Relations updated
        for ru_data in raw_result.get("relations_updated", []):
            try:
                ru = RelationUpdate.model_validate(ru_data)
                # Use update_relation_level if available, otherwise update via SQL
                await conn.execute(
                    """UPDATE relations SET
                        level = COALESCE($4, level),
                        context = COALESCE($5, context),
                        known_by_protagonist = COALESCE($6, known_by_protagonist)
                    WHERE game_id = $1
                      AND source_id = (SELECT id FROM entity_registry WHERE game_id=$1 AND LOWER(name)=LOWER($2) LIMIT 1)
                      AND target_id = (SELECT id FROM entity_registry WHERE game_id=$1 AND LOWER(name)=LOWER($3) LIMIT 1)
                      AND end_cycle IS NULL""",
                    self.game_id,
                    ru.source_ref, ru.target_ref,
                    ru.new_level, ru.new_context, ru.now_known,
                )
                stats["relations_updated"] += 1
            except Exception as e:
                stats["errors"].append(f"rel_update: {e}")

        # Relations ended
        for re_data in raw_result.get("relations_ended", []):
            try:
                re = RelationEnd.model_validate(re_data)
                await self.populator.end_relation(
                    conn, re.source_ref, re.target_ref,
                    re.relation_type, re.cycle, re.reason,
                )
                stats["relations_ended"] += 1
            except Exception as e:
                stats["errors"].append(f"rel_end: {e}")

        # Events scheduled
        for ev_data in raw_result.get("events_scheduled", []):
            try:
                ev = EventScheduledExtraction.model_validate(ev_data)
                await self.populator._schedule_event(conn, ev)
                stats["events_scheduled"] += 1
            except Exception as e:
                stats["errors"].append(f"event: {e}")

        # Facts
        for fact_data in raw_result.get("facts", []):
            try:
                fact_data.setdefault("cycle", cycle)
                fact = FactData.model_validate(fact_data)
                if await self.populator.create_fact(conn, fact):
                    stats["facts_created"] += 1
            except Exception as e:
                stats["errors"].append(f"fact: {e}")

        # Segment summary -> chronology
        summary = raw_result.get("segment_summary", "")
        if summary:
            await self.populator.save_chronology_entry(
                conn, cycle=cycle, summary=summary,
            )

        return stats
