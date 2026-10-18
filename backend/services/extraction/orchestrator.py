"""
LDVELH - Extraction Orchestrator

Post-turn background job, queued per game by the supervisor (pipeline/post_turn.py):
1. Resolver: entity annotations (for tooltips)
2. Extractors: entity/relation extraction (phase a: entities, phase b: arcs)
3. Re-apply entity_reveals (fix race condition with the narrator deltas applied at turn commit),
   share-locking the source message like the extractors (#23)
"""

import asyncio
import json
import logging
from uuid import UUID

import asyncpg

from config import get_settings
from llm.session import LLMSession

from kg.item_writes import write_item
from kg.populator import KnowledgeGraphPopulator
from repos import turns as turns_repo
from utils.log_safe import log_exception, safe_repr, safe_text

from .characters import CharactersExtractor
from .inventory import InventoryExtractor
from .locations import LocationsExtractor
from .narrative_arcs import NarrativeArcsExtractor
from .organizations import OrganizationsExtractor
from .progression import ProgressionExtractor
from .resolver import ResolutionMap, resolve_entities, build_span_annotations

logger = logging.getLogger(__name__)

EXTRACTOR_MAP = {
    "characters": CharactersExtractor,
    "locations": LocationsExtractor,
    "organizations": OrganizationsExtractor,
    "inventory": InventoryExtractor,
    "narrative_arcs": NarrativeArcsExtractor,
    "progression": ProgressionExtractor,
}

TYPE_TO_EXTRACTOR = {
    "character": "characters",
    "location": "locations",
    "organization": "organizations",
    "object": "inventory",
}


async def _apply_entity_reveals(
    conn: asyncpg.Connection, populator: KnowledgeGraphPopulator, entity_reveals: list
) -> None:
    """Each reveal in its own savepoint: a failing one is rolled back alone and logged."""
    errors: list[str] = []
    for reveal in entity_reveals:
        etype = reveal.get("entity_type")
        current_name = reveal.get("current_name")
        if etype == "character" and current_name:
            real = reveal.get("real_name")
            await write_item(conn, errors, "entity_reveal character",
                             lambda name=current_name, real=real:
                             populator.mark_character_known(conn, name, real),
                             "[EXTRACTION] ")
        elif etype == "location" and current_name:
            await write_item(conn, errors, "entity_reveal location",
                             lambda name=current_name:
                             populator.mark_location_accessible(conn, name),
                             "[EXTRACTION] ")


async def resolver_triggers(
    conn: asyncpg.Connection, game_id: UUID, resolution_map: ResolutionMap
) -> set[str]:
    """Extractors implied by mappings that are new and not yet in the game's registry."""
    candidates = [m for m in resolution_map.mappings
                  if m.is_new and m.entity_type in TYPE_TO_EXTRACTOR]
    if not candidates:
        return set()
    canonicals = list({m.canonical for m in candidates})
    rows = await conn.fetch(
        """SELECT c AS canonical FROM unnest($2::text[]) AS c
           WHERE EXISTS (SELECT 1 FROM entity_registry
                         WHERE game_id = $1 AND LOWER(name) = LOWER(c))""",
        game_id, canonicals,
    )
    known = {r["canonical"] for r in rows}
    return {TYPE_TO_EXTRACTOR[m.entity_type] for m in candidates
            if m.canonical not in known}


async def _compute_triggers(
    pool: asyncpg.Pool,
    game_id: UUID,
    triggers: list[str] | None,
    resolution_map: ResolutionMap | None,
) -> set[str]:
    """Narrator triggers plus resolver-inferred ones (new entities only), logged by origin."""
    narrator = {t for t in (triggers or []) if t in EXTRACTOR_MAP}
    inferred: set[str] = set()
    if resolution_map:
        try:
            async with pool.acquire() as conn:
                inferred = await resolver_triggers(conn, game_id, resolution_map)
        except Exception as e:
            log_exception(logger, logging.WARNING,
                          "[EXTRACTION] Resolver trigger lookup failed, using narrator triggers only",
                          e, debug_detail=get_settings().log_prompts)
    logger.info(
        f"[EXTRACTION] Triggers for game {game_id}: "
        f"narrator={sorted(narrator)} resolver={sorted(inferred)}"
    )
    return narrator | inferred


async def run_resolve_and_extract(
    pool: asyncpg.Pool,
    game_id: UUID,
    trigger_cycle: int,
    triggers: list[str] | None = None,
    *,
    session: LLMSession,
    assistant_message_id: UUID | None = None,
    message_content: str | None = None,
    narrator_deltas: dict | None = None,
) -> dict:
    """Background task: resolver → extractors → re-apply entity_reveals.

    Always runs the resolver (for tooltip annotations).
    Only runs extractors if triggers is non-empty.
    Re-applies entity_reveals after extraction to fix race condition.
    """
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
                        session=session,
                    )

                    if resolver_cost and isinstance(resolver_cost, dict):
                        total_cost += resolver_cost.get("cost_usd", 0)
                        result["resolver"] = resolver_cost
                else:
                    logger.info("[RESOLVER] No reference text available, skipping")
        except Exception as e:
            logger.warning(f"[RESOLVER] Failed, continuing without: {safe_repr(e)}")

        # =====================================================================
        # Phase 2: Extractors
        # Combine narrator triggers + resolver-inferred triggers from new entities
        # =====================================================================
        valid_triggers = sorted(await _compute_triggers(
            pool, game_id, triggers, resolution_map
        ))

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
                    EXTRACTOR_MAP[t](pool, game_id, session).run(
                        message_content=message_content,
                        narrator_deltas=narrator_deltas,
                        trigger_cycle=trigger_cycle,
                        resolution_map=resolution_map,
                        source_message_id=assistant_message_id,
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
                    log_exception(logger, logging.ERROR,
                                  f"[EXTRACTION] {trigger} raised exception", ext_result,
                                  debug_detail=get_settings().log_prompts)
                    result["extractors"][trigger] = {
                        "success": False, "error": safe_text(ext_result)
                    }
                else:
                    result["extractors"][trigger] = ext_result
                    cost = ext_result.get("cost") if isinstance(ext_result, dict) else None
                    if cost and isinstance(cost, dict):
                        total_cost += cost.get("cost_usd", 0)

            logger.info(
                f"[EXTRACTION] Complete: {_outcome_summary(result['extractors'])}, "
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
                async with pool.acquire() as conn, conn.transaction():
                    # Share-lock the source message: a rollback deleting it waits for
                    # these writes, and reveals of an already-deleted turn are skipped.
                    if assistant_message_id is None or \
                            await turns_repo.hold_source_message(conn, assistant_message_id):
                        await _apply_entity_reveals(conn, populator, entity_reveals)
                    else:
                        logger.info("[EXTRACTION] Source message gone, entity_reveals skipped")
        except Exception as e:
            logger.warning(f"[EXTRACTION] Re-apply entity_reveals failed: {safe_repr(e)}")

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
            logger.warning(f"[EXTRACTION] Store annotations failed: {safe_text(e)}")

        return result

    except Exception as e:
        log_exception(logger, logging.ERROR, "[EXTRACTION] Orchestrator failed", e,
                      debug_detail=get_settings().log_prompts)
        return {"success": False, "error": safe_text(e)}


# Backward compat alias
async def run_triggered_extraction(
    pool: asyncpg.Pool,
    game_id: UUID,
    trigger_cycle: int,
    triggers: list[str],
    *,
    session: LLMSession,
    assistant_message_id: UUID | None = None,
    message_content: str | None = None,
    narrator_deltas: dict | None = None,
) -> dict:
    """Backward-compatible wrapper."""
    return await run_resolve_and_extract(
        pool, game_id, trigger_cycle, triggers,
        session=session, assistant_message_id=assistant_message_id,
        message_content=message_content, narrator_deltas=narrator_deltas,
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


def _outcome(ext_result) -> str:
    """succeeded | partial (some items failed, the rest committed) | failed | skipped."""
    if not isinstance(ext_result, dict):
        return "failed"
    if ext_result.get("success"):
        return "succeeded"
    if ext_result.get("partial"):
        return "partial"
    return "skipped" if ext_result.get("skipped") else "failed"


def _outcome_summary(extractors: dict) -> str:
    """`2 succeeded, 1 partial, 0 failed, 0 skipped (3 extractors)`."""
    outcomes = [_outcome(r) for r in extractors.values()]
    counts = ", ".join(f"{outcomes.count(o)} {o}"
                       for o in ("succeeded", "partial", "failed", "skipped"))
    return f"{counts} ({len(outcomes)} extractors)"


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
        logger.warning(f"[EXTRACTION] Failed to update message cost: {safe_text(e)}")
