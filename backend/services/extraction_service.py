"""
LDVELH - Batch Extraction Service
End-of-cycle extraction: single LLM call (Sonnet), fire-and-forget.
Gauges, credits, and inventory hints are handled live by the narrator.
"""

import json
import logging
import time
from uuid import UUID

import asyncpg

from kg.reader import KnowledgeGraphReader
from kg.populator import KnowledgeGraphPopulator
from kg.specialized_populator import ExtractionPopulator
from prompts.extractor_prompts import (
    BATCH_EXTRACTION_SYSTEM,
    build_batch_extraction_prompt,
)
from schema import NarrativeExtraction
from services.llm_service import get_llm_service

logger = logging.getLogger(__name__)

_RETRY_ATTEMPTED: dict[str, bool] = {}


def _parse_participant_names(raw: list) -> list[str]:
    """Extract participant names from the 3 DB formats: dict with 'name', JSON string, plain string."""
    names = []
    for p in raw:
        if isinstance(p, dict):
            name = p.get("name", "")
        elif isinstance(p, str):
            # Try JSON string (e.g. '{"name": "Ossek"}')
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

# Guard against concurrent extractions for the same game
_extracting_games: set[str] = set()


async def run_batch_extraction(
    pool: asyncpg.Pool,
    game_id: UUID,
    trigger_cycle: int,
    provider_name: str = "anthropic",
    api_key: str | None = None,
) -> dict | None:
    """
    Fire-and-forget batch extraction for all unextracted cycles.

    Called on day_transition. Loads all unextracted assistant messages,
    sends them to Sonnet in a single LLM call, and populates the KG.
    """
    key = str(game_id)
    if key in _extracting_games:
        logger.warning(
            f"[EXTRACTION] Skipping: already extracting for game {game_id}"
        )
        return None
    _extracting_games.add(key)

    retry_key = f"{game_id}:{trigger_cycle}"
    t0 = time.perf_counter()

    try:
        reader = KnowledgeGraphReader(pool, game_id)
        populator = KnowledgeGraphPopulator(pool, game_id)
        llm = get_llm_service()

        async with pool.acquire() as conn:
            # 1. Read extraction tracking
            game = await reader.get_game(conn)
            if not game:
                logger.error(f"[BATCH] Game {game_id} not found")
                return None

            from_cycle = game.get("extracted_up_to_cycle") or 0

            # 2. Load all unextracted assistant messages
            messages = await reader.get_unextracted_messages(
                conn, from_cycle, trigger_cycle
            )
            if not messages:
                logger.info(
                    f"[BATCH] No unextracted messages for game {game_id} "
                    f"(cycles {from_cycle+1}-{trigger_cycle})"
                )
                # Still update tracking
                await populator.update_extracted_cycle(conn, trigger_cycle)
                return {"skipped": True, "reason": "no_messages"}

            # 3. Load context: known entities + active arcs
            entities = await reader.get_entities(conn)
            known_entities = [e["name"] for e in entities]

            active_arcs = await reader.get_active_arcs(conn)
            known_arc_titles = [a["title"] for a in active_arcs]

            arc_summaries = []
            for arc in active_arcs:
                participants = _parse_participant_names(arc.get("participants") or [])
                arc_summaries.append({
                    "title": arc["title"],
                    "domain": arc.get("domain", "personal"),
                    "intensity": arc.get("intensity", 3),
                    "participants": participants,
                })

            stub_locations = await reader.get_stub_locations(conn)

        # 4. Collect narrative texts, inventory hints, and narrator hints
        narrative_texts = [m["content"] for m in messages]
        all_inventory_hints = []
        all_narrator_hints = []
        for m in messages:
            deltas = m.get("narrator_deltas")
            if deltas and isinstance(deltas, dict):
                all_inventory_hints.extend(deltas.get("inventory_hints", []))
                if deltas.get("hints"):
                    all_narrator_hints.append(deltas["hints"])

        logger.info(
            f"[BATCH] Extracting {len(messages)} messages for game {game_id} "
            f"(cycles {from_cycle+1}-{trigger_cycle})"
        )

        # 5. Single LLM call (Sonnet) — tool_use with text fallback
        t_llm = time.perf_counter()
        user_prompt = build_batch_extraction_prompt(
            narrative_texts=narrative_texts,
            cycle=trigger_cycle,
            known_entities=known_entities,
            known_arc_titles=known_arc_titles if known_arc_titles else None,
            inventory_hints=all_inventory_hints if all_inventory_hints else None,
            narrator_hints=all_narrator_hints if all_narrator_hints else None,
            stub_locations=stub_locations if stub_locations else None,
            active_arc_details=arc_summaries if arc_summaries else None,
        )

        from schema.extraction import get_extraction_tool_schema

        raw_result = await llm.extract_structured(
            system_prompt=BATCH_EXTRACTION_SYSTEM,
            user_message=user_prompt,
            tool_name="extract_narrative",
            tool_description="Extract entities, facts, relations, arcs from narrative text",
            schema=get_extraction_tool_schema(),
            provider_name=provider_name,
            api_key=api_key,
        )
        extraction_cost = getattr(llm, "_last_call_cost", None)
        logger.info(
            f"[BATCH] LLM call completed in {(time.perf_counter() - t_llm)*1000:.0f}ms"
            f" (cost: ${extraction_cost.get('cost_usd', '?') if extraction_cost else '?'})"
        )

        if not raw_result:
            logger.warning(f"[BATCH] LLM returned empty result for game {game_id}")
            return {"success": False, "error": "empty_llm_response"}

        # 6. Add cycle to facts and relations
        for fact in raw_result.get("facts", []):
            if "cycle" not in fact:
                fact["cycle"] = trigger_cycle
        for rel in raw_result.get("relations_created", []):
            if "cycle" not in rel:
                rel["cycle"] = trigger_cycle

        # 7. Validate and populate KG
        stats = {}
        async with pool.acquire() as conn:
            extraction_populator = ExtractionPopulator(pool, game_id)
            await extraction_populator.load_registry(conn)

            try:
                # Add required fields for NarrativeExtraction
                raw_result["cycle"] = trigger_cycle
                raw_result.setdefault("current_location_ref", "")
                raw_result.setdefault("key_npcs_present", [])
                # Batch doesn't extract protagonist state (handled live)
                raw_result.setdefault("gauge_changes", [])
                raw_result.setdefault("credit_transactions", [])
                raw_result.setdefault("inventory_changes", [])

                extraction = NarrativeExtraction.model_validate(raw_result)
                stats = await extraction_populator.process_extraction(extraction)
            except Exception as e:
                logger.warning(f"[BATCH] Validation error, processing raw: {e}")
                stats = await _process_raw_batch(
                    extraction_populator, conn, raw_result, trigger_cycle
                )

            # 8. Formalize inventory hints into proper objects + inventory entries
            if all_inventory_hints:
                await _formalize_inventory_hints(
                    extraction_populator, conn, all_inventory_hints, trigger_cycle
                )

            # 9. Mark messages as extracted + store extraction cost on last message
            message_ids = [m["id"] for m in messages]
            await conn.execute(
                "UPDATE messages SET extracted = true WHERE id = ANY($1)",
                message_ids,
            )
            if extraction_cost and message_ids:
                last_msg_id = message_ids[-1]
                await conn.execute(
                    """UPDATE messages SET narrator_deltas =
                       COALESCE(narrator_deltas, '{}'::jsonb)
                       || jsonb_build_object('extraction_cost', $2::jsonb)
                    WHERE id = $1""",
                    last_msg_id,
                    json.dumps(extraction_cost),
                )

            # 10. Save chronology entry
            summary = raw_result.get("segment_summary", "")
            if summary:
                await extraction_populator.save_chronology_entry(
                    conn,
                    trigger_cycle,
                    summary=summary,
                )

            # 11. Update extraction tracking
            await populator.update_extracted_cycle(conn, trigger_cycle)

            # 12. Update last_extraction_time from latest message
            last_time = None
            for m in reversed(messages):
                deltas = m.get("narrator_deltas")
                if deltas and isinstance(deltas, dict):
                    # Time stored at message level
                    last_time = m.get("time")
                    if last_time:
                        break
            if last_time:
                await conn.execute(
                    "UPDATE games SET last_extraction_time=$1 WHERE id=$2",
                    last_time, game_id,
                )
                logger.info(f"[BATCH] Updated last_extraction_time to {last_time}")

        elapsed = (time.perf_counter() - t0) * 1000
        logger.info(
            f"[BATCH] Extraction complete for game {game_id} in {elapsed:.0f}ms: "
            f"{json.dumps(stats, default=str)}"
        )

        # Clear retry flag on success
        _RETRY_ATTEMPTED.pop(retry_key, None)

        return {"success": True, "stats": stats, "duration_ms": int(elapsed)}

    except Exception as e:
        logger.error(f"[BATCH] Extraction failed for game {game_id}: {e}")
        import traceback
        traceback.print_exc()

        # Simple retry: once only
        if retry_key not in _RETRY_ATTEMPTED:
            _RETRY_ATTEMPTED[retry_key] = True
            logger.info(f"[BATCH] Scheduling retry for game {game_id}")
            import asyncio
            asyncio.create_task(run_batch_extraction(pool, game_id, trigger_cycle, provider_name, api_key))

        return {"success": False, "error": str(e)}

    finally:
        _extracting_games.discard(key)


async def _process_raw_batch(
    populator: ExtractionPopulator,
    conn,
    data: dict,
    cycle: int,
) -> dict:
    """Process raw batch extraction when Pydantic validation fails."""
    stats = {
        "facts_created": 0,
        "entities_created": 0,
        "objects_created": 0,
        "relations_created": 0,
        "errors": [],
    }

    # Facts
    for fact_data in data.get("facts", []):
        try:
            from schema import FactData
            if "cycle" not in fact_data:
                fact_data["cycle"] = cycle
            fact = FactData.model_validate(fact_data)
            result = await populator.create_fact(conn, fact)
            if result:
                stats["facts_created"] += 1
        except Exception as e:
            stats["errors"].append(f"fact: {e}")

    # Entities
    for entity_data in data.get("entities_created", []):
        try:
            from schema import EntityCreation
            entity = EntityCreation.model_validate(entity_data)
            await populator._process_entity_creation(conn, entity, cycle)
            stats["entities_created"] += 1
        except Exception as e:
            stats["errors"].append(f"entity: {e}")

    # Objects
    for obj_data in data.get("objects_created", []):
        try:
            from schema import ObjectCreation
            obj = ObjectCreation.model_validate(obj_data)
            await populator._process_object_creation(conn, obj, cycle)
            stats["objects_created"] += 1
        except Exception as e:
            stats["errors"].append(f"object: {e}")

    # Relations
    for rel_data in data.get("relations_created", []):
        try:
            from schema import RelationData
            relation_dict = rel_data.get("relation", rel_data)
            rel_cycle = rel_data.get("cycle", cycle)
            relation = RelationData.model_validate(relation_dict)
            result = await populator.create_relation(conn, relation, rel_cycle)
            if result:
                stats["relations_created"] += 1
        except Exception as e:
            stats["errors"].append(f"relation: {e}")

    # Ambient updates
    for amb_data in data.get("ambient_updates", []):
        try:
            from schema.extraction import AmbientUpdate
            amb = AmbientUpdate.model_validate(amb_data)
            await populator.update_entity(
                conn, amb.entity_type, amb.entity_ref, {"ambient": amb.ambient}
            )
        except Exception as e:
            stats["errors"].append(f"ambient: {e}")

    return stats


async def _formalize_inventory_hints(
    populator: ExtractionPopulator,
    conn,
    inventory_hints: list[dict],
    cycle: int,
) -> int:
    """
    Convert narrator inventory_hints into proper objects + inventory entries.
    Called during batch extraction to formalize pending items.
    """
    created = 0
    for hint in inventory_hints:
        action = hint.get("action", "")
        if action != "acquire":
            continue

        item_name = hint.get("item_name", "")
        if not item_name:
            continue

        try:
            from schema import ObjectCreation
            obj = ObjectCreation(
                name=item_name,
                category="misc",
                description=hint.get("item_description", ""),
                transportable=True,
                stackable=False,
                base_value=None,
                quantity=hint.get("quantity", 1),
                from_hint=item_name,
            )
            await populator._process_object_creation(conn, obj, cycle)
            created += 1
        except Exception as e:
            logger.warning(f"[BATCH] Failed to formalize inventory hint '{item_name}': {e}")

    if created:
        logger.info(f"[BATCH] Formalized {created} inventory hints into objects")
    return created
