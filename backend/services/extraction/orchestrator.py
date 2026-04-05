"""
LDVELH - Extraction Orchestrator
Runs triggered extractors in parallel via asyncio.gather.
"""

import asyncio
import json
import logging
from uuid import UUID

import asyncpg

from .characters import CharactersExtractor
from .inventory import InventoryExtractor
from .locations import LocationsExtractor
from .narrative_arcs import NarrativeArcsExtractor
from .organizations import OrganizationsExtractor

logger = logging.getLogger(__name__)

EXTRACTOR_MAP = {
    "characters": CharactersExtractor,
    "locations": LocationsExtractor,
    "organizations": OrganizationsExtractor,
    "inventory": InventoryExtractor,
    "narrative_arcs": NarrativeArcsExtractor,
}

# Guard against concurrent extractions for the same game
_extracting_games: set[str] = set()


async def run_triggered_extraction(
    pool: asyncpg.Pool,
    game_id: UUID,
    trigger_cycle: int,
    triggers: list[str],
    provider_name: str = "anthropic",
    api_key: str | None = None,
    assistant_message_id: UUID | None = None,
) -> dict:
    """Run triggered extractors in parallel.

    Each extractor runs independently — one failing does not block others.
    Returns aggregated results from all extractors.
    """
    key = str(game_id)
    if key in _extracting_games:
        logger.warning(
            f"[EXTRACTION] Skipping: already extracting for game {game_id}"
        )
        return {"skipped": True, "reason": "concurrent"}
    _extracting_games.add(key)

    try:
        # Filter to valid trigger names
        valid_triggers = [t for t in triggers if t in EXTRACTOR_MAP]
        if not valid_triggers:
            logger.info(f"[EXTRACTION] No valid triggers in {triggers}")
            return {"skipped": True, "reason": "no_valid_triggers"}

        logger.info(
            f"[EXTRACTION] Running {len(valid_triggers)} extractors "
            f"for game {game_id}: {valid_triggers}"
        )

        # Create extractor instances
        tasks = [
            EXTRACTOR_MAP[t](pool, game_id, provider_name, api_key).run(trigger_cycle)
            for t in valid_triggers
        ]

        # Run in parallel
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Aggregate results and costs
        aggregated = {"extractors": {}}
        total_cost = 0.0
        for trigger, result in zip(valid_triggers, results):
            if isinstance(result, Exception):
                logger.error(
                    f"[EXTRACTION] {trigger} raised exception: {result}",
                    exc_info=result,
                )
                aggregated["extractors"][trigger] = {
                    "success": False, "error": str(result)
                }
            else:
                aggregated["extractors"][trigger] = result
                cost = result.get("cost") if isinstance(result, dict) else None
                if cost and isinstance(cost, dict):
                    total_cost += cost.get("cost_usd", 0)

        successes = sum(
            1 for r in aggregated["extractors"].values()
            if isinstance(r, dict) and r.get("success")
        )
        logger.info(
            f"[EXTRACTION] Complete: {successes}/{len(valid_triggers)} succeeded, "
            f"total cost: ${total_cost:.6f}"
        )

        # Update the assistant message with extraction cost
        if assistant_message_id and total_cost > 0:
            await _append_extraction_cost(
                pool, assistant_message_id, aggregated, total_cost
            )

        return aggregated

    except Exception as e:
        logger.error(f"[EXTRACTION] Orchestrator failed: {e}", exc_info=True)
        return {"success": False, "error": str(e)}

    finally:
        _extracting_games.discard(key)


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

            # Build extraction cost summary
            extraction_cost = {
                "cost_usd": round(total_cost, 6),
                "extractors": {},
            }
            for name, result in aggregated.get("extractors", {}).items():
                if isinstance(result, dict) and result.get("cost"):
                    c = result["cost"]
                    extraction_cost["extractors"][name] = {
                        "cost_usd": c.get("cost_usd", 0),
                        "input_tokens": c.get("input_tokens", 0),
                        "output_tokens": c.get("output_tokens", 0),
                        "model": c.get("model", ""),
                    }

            deltas["extraction_cost"] = extraction_cost

            # Also update total cost if narration cost exists
            narration_cost = deltas.get("cost", {}).get("cost_usd", 0)
            if narration_cost:
                deltas["total_cost_usd"] = round(narration_cost + total_cost, 6)

            await conn.execute(
                "UPDATE messages SET narrator_deltas = $1 WHERE id = $2",
                deltas,
                message_id,
            )
            logger.info(
                f"[EXTRACTION] Updated message {message_id} with extraction cost: "
                f"${total_cost:.6f}"
            )

    except Exception as e:
        logger.warning(f"[EXTRACTION] Failed to update message cost: {e}")
