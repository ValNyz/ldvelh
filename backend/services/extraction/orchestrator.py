"""
LDVELH - Extraction Orchestrator

Background task launched from routes.py every turn:
1. Resolver: entity annotations (for tooltips)
2. Extractors: entity/relation extraction (phase a: entities, phase b: arcs)
3. Re-apply entity_reveals (fix race condition with apply_narrator_deltas)
"""

import asyncio
import json
import logging
from uuid import UUID

import asyncpg

from kg.populator import KnowledgeGraphPopulator

from .characters import CharactersExtractor
from .inventory import InventoryExtractor
from .locations import LocationsExtractor
from .narrative_arcs import NarrativeArcsExtractor
from .organizations import OrganizationsExtractor
from .progression import ProgressionExtractor
from .resolver import resolve_entities, build_span_annotations

logger = logging.getLogger(__name__)

EXTRACTOR_MAP = {
    "characters": CharactersExtractor,
    "locations": LocationsExtractor,
    "organizations": OrganizationsExtractor,
    "inventory": InventoryExtractor,
    "narrative_arcs": NarrativeArcsExtractor,
    "progression": ProgressionExtractor,
}

# Guard against concurrent extractions for the same game
_extracting_games: set[str] = set()


async def run_resolve_and_extract(
    pool: asyncpg.Pool,
    game_id: UUID,
    trigger_cycle: int,
    triggers: list[str] | None = None,
    provider_name: str = "anthropic",
    api_key: str | None = None,
    assistant_message_id: UUID | None = None,
    message_content: str | None = None,
    narrator_deltas: dict | None = None,
) -> dict:
    """Background task: resolver → extractors → re-apply entity_reveals.

    Always runs the resolver (for tooltip annotations).
    Only runs extractors if triggers is non-empty.
    Re-applies entity_reveals after extraction to fix race condition.
    Called via asyncio.create_task from routes.py.
    """
    key = str(game_id)
    if key in _extracting_games:
        logger.warning(
            f"[EXTRACTION] Skipping: already extracting for game {game_id}"
        )
        return {"skipped": True, "reason": "concurrent"}
    _extracting_games.add(key)

    try:
        result = {"resolver": None, "extractors": {}}
        total_cost = 0.0
        narrator_deltas = narrator_deltas or {}

        # =====================================================================
        # Phase 1: Resolver (always runs)
        # =====================================================================
        resolution_map = None

        try:
            if assistant_message_id and message_content:
                async with pool.acquire() as conn:
                    prev_msg = await conn.fetchrow(
                        """SELECT content, narrator_context FROM messages
                           WHERE game_id = $1 AND role = 'assistant'
                             AND id != $2
                           ORDER BY sequence DESC LIMIT 1""",
                        game_id, assistant_message_id,
                    )

                if prev_msg and prev_msg["content"]:
                    prev_text = prev_msg["content"]
                    prev_annotations = prev_msg["narrator_context"]
                else:
                    prev_text, prev_annotations = await _build_first_turn_reference(
                        pool, game_id
                    )

                if prev_text:
                    resolution_map, resolver_cost = await resolve_entities(
                        pool, game_id,
                        previous_response=prev_text,
                        previous_annotations=prev_annotations,
                        current_response=message_content,
                        provider_name=provider_name,
                        api_key=api_key,
                    )

                    if resolver_cost and isinstance(resolver_cost, dict):
                        total_cost += resolver_cost.get("cost_usd", 0)
                        result["resolver"] = resolver_cost
                else:
                    logger.info("[RESOLVER] No reference text available, skipping")
        except Exception as e:
            logger.warning(f"[RESOLVER] Failed, continuing without: {e}")

        # =====================================================================
        # Phase 2: Extractors
        # Combine narrator triggers + resolver-inferred triggers from new entities
        # =====================================================================
        trigger_set = set(t for t in (triggers or []) if t in EXTRACTOR_MAP)

        # Resolver can infer additional extractors from new entity types
        if resolution_map:
            TYPE_TO_EXTRACTOR = {
                "character": "characters",
                "location": "locations",
                "organization": "organizations",
                "object": "inventory",
            }
            for mapping in resolution_map.mappings:
                extractor = TYPE_TO_EXTRACTOR.get(mapping.entity_type)
                if extractor and extractor not in trigger_set:
                    trigger_set.add(extractor)
                    logger.info(
                        f"[EXTRACTION] Resolver added trigger '{extractor}' "
                        f"(entity: {mapping.canonical})"
                    )

        valid_triggers = list(trigger_set)

        if valid_triggers and message_content:
            logger.info(
                f"[EXTRACTION] Running {len(valid_triggers)} extractors "
                f"for game {game_id}: {valid_triggers}"
            )

            # Phase 2a: entity extractors (no cross-entity references)
            ENTITY_EXTRACTORS = {"characters", "locations", "organizations", "inventory"}
            # Phase 2b: relation extractors (reference entities created in 2a)
            RELATION_EXTRACTORS = {"narrative_arcs", "progression"}

            phase_a = [t for t in valid_triggers if t in ENTITY_EXTRACTORS]
            phase_b = [t for t in valid_triggers if t in RELATION_EXTRACTORS]

            async def _run_phase(trigger_names):
                tasks = [
                    EXTRACTOR_MAP[t](pool, game_id, provider_name, api_key).run(
                        message_content=message_content,
                        narrator_deltas=narrator_deltas,
                        trigger_cycle=trigger_cycle,
                        resolution_map=resolution_map,
                    )
                    for t in trigger_names
                ]
                return list(zip(trigger_names, await asyncio.gather(*tasks, return_exceptions=True)))

            all_results = []
            if phase_a:
                all_results.extend(await _run_phase(phase_a))
            if phase_b:
                all_results.extend(await _run_phase(phase_b))

            for trigger, ext_result in all_results:
                if isinstance(ext_result, Exception):
                    logger.error(
                        f"[EXTRACTION] {trigger} raised exception: {ext_result}",
                        exc_info=ext_result,
                    )
                    result["extractors"][trigger] = {
                        "success": False, "error": str(ext_result)
                    }
                else:
                    result["extractors"][trigger] = ext_result
                    cost = ext_result.get("cost") if isinstance(ext_result, dict) else None
                    if cost and isinstance(cost, dict):
                        total_cost += cost.get("cost_usd", 0)

            successes = sum(
                1 for r in result["extractors"].values()
                if isinstance(r, dict) and r.get("success")
            )
            logger.info(
                f"[EXTRACTION] Complete: {successes}/{len(valid_triggers)} succeeded, "
                f"total cost: ${total_cost:.6f}"
            )

            # Update assistant message with extraction cost
            if assistant_message_id and total_cost > 0:
                await _append_extraction_cost(
                    pool, assistant_message_id, result, total_cost
                )

        # =====================================================================
        # Phase 3: Re-apply entity_reveals (entities now exist after extraction)
        # =====================================================================
        try:
            entity_reveals = narrator_deltas.get("entity_reveals", [])
            if entity_reveals:
                populator = KnowledgeGraphPopulator(pool, game_id)
                async with pool.acquire() as conn:
                    for reveal in entity_reveals:
                        etype = reveal.get("entity_type")
                        current_name = reveal.get("current_name")
                        real_name = reveal.get("real_name")
                        if etype == "character" and current_name:
                            await populator.mark_character_known(
                                conn, current_name, real_name
                            )
                        elif etype == "location" and current_name:
                            await populator.mark_location_accessible(
                                conn, current_name
                            )
        except Exception as e:
            logger.warning(f"[EXTRACTION] Re-apply entity_reveals failed: {e}")

        # =====================================================================
        # Phase 4: Store annotations (after extractors, so entities exist in DB)
        # =====================================================================
        try:
            if resolution_map and message_content and assistant_message_id:
                annotations = build_span_annotations(
                    message_content, resolution_map
                )
                if annotations:
                    async with pool.acquire() as conn:
                        await conn.execute(
                            "UPDATE messages SET narrator_context = $1 WHERE id = $2",
                            annotations,
                            assistant_message_id,
                        )
                    logger.info(
                        f"[RESOLVER] Stored {len(annotations)} entity annotations"
                    )
        except Exception as e:
            logger.warning(f"[EXTRACTION] Store annotations failed: {e}")

        return result

    except Exception as e:
        logger.error(f"[EXTRACTION] Orchestrator failed: {e}", exc_info=True)
        return {"success": False, "error": str(e)}

    finally:
        _extracting_games.discard(key)


# Backward compat alias
async def run_triggered_extraction(
    pool: asyncpg.Pool,
    game_id: UUID,
    trigger_cycle: int,
    triggers: list[str],
    provider_name: str = "anthropic",
    api_key: str | None = None,
    assistant_message_id: UUID | None = None,
    message_content: str | None = None,
    narrator_deltas: dict | None = None,
) -> dict:
    """Backward-compatible wrapper."""
    return await run_resolve_and_extract(
        pool, game_id, trigger_cycle, triggers,
        provider_name, api_key, assistant_message_id,
        message_content, narrator_deltas,
    )


async def _build_first_turn_reference(
    pool: asyncpg.Pool, game_id: UUID
) -> tuple[str, list]:
    """Build a synthetic reference text for first-turn entity resolution.

    When no previous assistant message exists, we construct a fake "MESSAGE 1"
    from known DB entities so the resolver can map mentions in the first response.
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT er.name, er.entity_type
               FROM entity_registry er
               WHERE er.game_id = $1
                 AND er.entity_type IN ('character', 'location', 'organization')
               ORDER BY er.entity_type, er.name""",
            game_id,
        )

    if not rows:
        return "", None

    parts = []
    annotations = []
    offset = 0
    for r in rows:
        name = r["name"]
        etype = r["entity_type"]
        line = f"{name} [= {name}]"
        start = offset
        end = offset + len(name)
        annotations.append([start, end, name, etype])
        parts.append(line)
        offset += len(line) + 1  # +1 for newline

    text = "\n".join(parts)
    return text, annotations


async def _append_extraction_cost(
    pool: asyncpg.Pool,
    message_id: UUID,
    aggregated: dict,
    total_cost: float,
) -> None:
    """Append extraction cost to the assistant message's narrator_deltas."""
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchval(
                "SELECT narrator_deltas FROM messages WHERE id = $1",
                message_id,
            )
            deltas = json.loads(row) if isinstance(row, str) else (row or {})

            extraction_cost = {
                "cost_usd": round(total_cost, 6),
                "extractors": {},
            }
            for name, ext_result in aggregated.get("extractors", {}).items():
                if isinstance(ext_result, dict) and ext_result.get("cost"):
                    c = ext_result["cost"]
                    extraction_cost["extractors"][name] = {
                        "cost_usd": c.get("cost_usd", 0),
                        "input_tokens": c.get("input_tokens", 0),
                        "output_tokens": c.get("output_tokens", 0),
                        "model": c.get("model", ""),
                    }

            deltas["extraction_cost"] = extraction_cost

            narration_cost = deltas.get("cost", {}).get("cost_usd", 0)
            if narration_cost:
                deltas["total_cost_usd"] = round(narration_cost + total_cost, 6)

            await conn.execute(
                "UPDATE messages SET narrator_deltas = $1 WHERE id = $2",
                deltas,
                message_id,
            )
            logger.info(
                f"[EXTRACTION] Updated message {message_id} with cost: ${total_cost:.6f}"
            )

    except Exception as e:
        logger.warning(f"[EXTRACTION] Failed to update message cost: {e}")
