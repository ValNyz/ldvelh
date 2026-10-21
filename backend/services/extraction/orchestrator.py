"""
LDVELH - Extraction Orchestrator

Post-turn background job, queued per game by the supervisor (pipeline/post_turn.py), one
function per phase:
1. Resolver v2 (always): the scene of the turn and its candidates, the identity
   decisions (model calls with no pool connection held), then their application in the turn's unit of work,
   share-locking the source message: stubs created by the identity service,
   entity_mentions, identity_events (#154).
2. Extractors: run for the entity types the turn really created or left bare, plus the
   narrator's extraction_triggers; they reference the scene's entities by handle (phase a:
   entities, phase b: arcs and progression).
3. Re-apply entity_reveals (fix race condition with the narrator deltas applied at turn
   commit), in the turn's unit of work, share-locking the source message like the
   extractors (#23, #105).
"""

import asyncio
import logging
from uuid import UUID

import asyncpg

from config import get_settings
from domain.errors import SourceMessageGone
from domain.identity import SceneEntity, TurnRef, TurnResolution
from llm.session import LLMSession
from repos import messages
from repos.pooled import PooledReads
from repos.uow import uow
from services.identity.reveals import apply_entity_reveals
from services.identity.scene import collect_scene_context
from services.identity.service import IdentityService
from utils.log_safe import log_exception, safe_text

from .characters import CharactersExtractor
from .inventory import InventoryExtractor
from .locations import LocationsExtractor
from .narrative_arcs import NarrativeArcsExtractor
from .organizations import OrganizationsExtractor
from .progression import ProgressionExtractor

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
# Phase a: entity extractors (no cross-entity references); phase b: relation extractors
# (they reference entities phase a may have enriched).
ENTITY_EXTRACTORS = ("characters", "locations", "organizations", "inventory")
RELATION_EXTRACTORS = ("narrative_arcs", "progression")


def resolver_triggers(resolution: TurnResolution | None) -> set[str]:
    """Extractors of the entity types the turn created or linked while still bare."""
    if resolution is None:
        return set()
    return {
        TYPE_TO_EXTRACTOR[t] for t in resolution.new_types if t in TYPE_TO_EXTRACTOR
    }


def compute_triggers(
    game_id: UUID, triggers: list[str] | None, resolution: TurnResolution | None
) -> list[str]:
    """Narrator triggers plus resolver ones, logged by origin, in a stable order."""
    narrator = {t for t in (triggers or []) if t in EXTRACTOR_MAP}
    inferred = resolver_triggers(resolution)
    logger.info(
        f"[EXTRACTION] Triggers for game {game_id}: "
        f"narrator={sorted(narrator)} resolver={sorted(inferred)}"
    )
    return sorted(narrator | inferred)


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
    turn_id: UUID | None = None,
) -> dict:
    """Background task: resolver v2 → extractors → re-apply entity_reveals.

    Always runs the resolver (mentions, tooltips); runs the extractors only when the turn
    triggers some. World writes are journaled under `turn_id` when given (#105).
    """
    try:
        deltas = narrator_deltas or {}
        turn = (
            TurnRef(turn_id, assistant_message_id, trigger_cycle)
            if assistant_message_id
            else None
        )
        resolution = await resolve_phase(
            pool, session, game_id, turn, message_content, deltas
        )
        result = {"resolver": _resolver_summary(resolution), "extractors": {}}
        names = compute_triggers(game_id, triggers, resolution)
        if names and message_content:
            result["extractors"] = await extract_phase(
                pool,
                session,
                game_id,
                names,
                message_content,
                deltas,
                trigger_cycle,
                resolution.scene_entities if resolution else [],
                source_message_id=assistant_message_id,
                turn_id=turn_id,
            )
        if resolution is not None or result["extractors"]:
            # The resolver is a paid call on every turn, with or without extractors.
            await _record_cost(pool, assistant_message_id, result)
        await reveal_phase(pool, game_id, deltas, assistant_message_id, turn_id)
        return result
    except Exception as e:
        log_exception(
            logger,
            logging.ERROR,
            "[EXTRACTION] Orchestrator failed",
            e,
            debug_detail=get_settings().log_prompts,
        )
        return {"success": False, "error": safe_text(e)}


# =============================================================================
# Phase 1: resolver v2
# =============================================================================


async def resolve_phase(
    pool: asyncpg.Pool,
    session: LLMSession,
    game_id: UUID,
    turn: TurnRef | None,
    narration: str | None,
    deltas: dict,
) -> TurnResolution | None:
    """The turn's identity resolution (spec §4.5): the scene and the candidates read on
    a connection, the model cascade with none held (#94), the application in the turn's
    unit of work. None when there is nothing to resolve, when the source message is gone
    (rolled back) or when it failed (the turn goes on)."""
    if turn is None or not narration:
        return None
    try:
        async with pool.acquire() as conn:
            identity = await IdentityService.for_game(conn, game_id)
            scene = await collect_scene_context(conn, game_id, turn.message_id, deltas)
            candidates = await identity.block(conn, narration, scene)
        decided = await identity.decide(
            PooledReads(pool), session, narration, scene, candidates
        )
        async with pool.acquire() as conn:
            async with uow(conn, turn.turn_id, source_message_id=turn.message_id):
                return await identity.apply_resolution(
                    conn, turn, narration, scene, decided
                )
    except SourceMessageGone:
        logger.info("[IDENTITY] Source message gone, turn resolution skipped")
    except Exception as e:
        log_exception(
            logger,
            logging.WARNING,
            "[IDENTITY] Turn resolution failed, continuing without",
            e,
            debug_detail=get_settings().log_prompts,
        )
    return None


def _resolver_summary(resolution: TurnResolution | None) -> dict | None:
    """Counts and cost of the resolution (no story text)."""
    if resolution is None:
        return None
    return {
        **resolution.stats(),
        "cost_usd": resolution.cost_usd(),
        "usage": resolution.usage,
    }


# =============================================================================
# Phase 2: extractors
# =============================================================================


async def extract_phase(
    pool: asyncpg.Pool,
    session: LLMSession,
    game_id: UUID,
    names: list[str],
    message_content: str,
    deltas: dict,
    trigger_cycle: int,
    scene_entities: list[SceneEntity],
    *,
    source_message_id: UUID | None,
    turn_id: UUID | None,
) -> dict:
    """Entity extractors, then relation extractors; each one's result (or failure)."""
    logger.info(
        f"[EXTRACTION] Running {len(names)} extractors for game {game_id}: {names}"
    )

    async def run(trigger_names: list[str]) -> list[tuple[str, object]]:
        tasks = [
            EXTRACTOR_MAP[t](pool, game_id, session).run(
                message_content=message_content,
                narrator_deltas=deltas,
                trigger_cycle=trigger_cycle,
                scene_entities=scene_entities,
                source_message_id=source_message_id,
                turn_id=turn_id,
            )
            for t in trigger_names
        ]
        return list(
            zip(trigger_names, await asyncio.gather(*tasks, return_exceptions=True))
        )

    outcomes = []
    for phase in (ENTITY_EXTRACTORS, RELATION_EXTRACTORS):
        if chosen := [t for t in names if t in phase]:
            outcomes.extend(await run(chosen))
    extractors = {name: _extractor_result(name, out) for name, out in outcomes}
    logger.info(f"[EXTRACTION] Complete: {_outcome_summary(extractors)}")
    return extractors


def _extractor_result(name: str, ext_result) -> dict:
    if isinstance(ext_result, Exception):
        log_exception(
            logger,
            logging.ERROR,
            f"[EXTRACTION] {name} raised exception",
            ext_result,
            debug_detail=get_settings().log_prompts,
        )
        return {"success": False, "error": safe_text(ext_result)}
    return ext_result


def total_cost(result: dict) -> float:
    """What the resolver and the extractors of a turn cost."""
    total = (result.get("resolver") or {}).get("cost_usd", 0) or 0
    for ext_result in result.get("extractors", {}).values():
        cost = ext_result.get("cost") if isinstance(ext_result, dict) else None
        if cost and isinstance(cost, dict):
            total += cost.get("cost_usd", 0)
    return total


async def _record_cost(
    pool: asyncpg.Pool, message_id: UUID | None, result: dict
) -> None:
    cost = total_cost(result)
    logger.info(f"[EXTRACTION] Total cost: ${cost:.6f}")
    if message_id and cost > 0:
        await _append_extraction_cost(pool, message_id, result, cost)


# =============================================================================
# Phase 3: re-apply entity_reveals
# =============================================================================


async def reveal_phase(
    pool: asyncpg.Pool,
    game_id: UUID,
    deltas: dict,
    message_id: UUID | None,
    turn_id: UUID | None,
) -> None:
    """The narrator's entity_reveals again, now that the turn's entities exist; the
    source message share-locked: a rollback deleting it waits for these writes, and the
    reveals of an already-deleted turn are skipped."""
    entity_reveals = deltas.get("entity_reveals", [])
    if not entity_reveals:
        return
    try:
        async with pool.acquire() as conn:
            async with uow(conn, turn_id, source_message_id=message_id):
                await apply_entity_reveals(
                    conn,
                    await IdentityService.for_game(conn, game_id),
                    entity_reveals,
                    turn_id=None,
                    source="reveal",
                    log_prefix="[EXTRACTION] ",
                )
    except SourceMessageGone:
        logger.info("[EXTRACTION] Source message gone, entity_reveals skipped")
    except Exception as e:
        log_exception(
            logger,
            logging.WARNING,
            "[EXTRACTION] Re-apply entity_reveals failed",
            e,
            debug_detail=get_settings().log_prompts,
        )


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
    counts = ", ".join(
        f"{outcomes.count(o)} {o}"
        for o in ("succeeded", "partial", "failed", "skipped")
    )
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
            deltas = await messages.narrator_deltas(conn, message_id)
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

            await messages.set_narrator_deltas(conn, message_id, deltas)
            logger.info(
                f"[EXTRACTION] Updated message {message_id} with cost: ${total_cost:.6f}"
            )

    except Exception as e:
        logger.warning(f"[EXTRACTION] Failed to update message cost: {safe_text(e)}")
