"""
LDVELH - Extraction Orchestrator
Runs triggered extractors in parallel via asyncio.gather.
"""

import asyncio
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

        # Aggregate results
        aggregated = {"extractors": {}}
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

        successes = sum(
            1 for r in aggregated["extractors"].values()
            if isinstance(r, dict) and r.get("success")
        )
        logger.info(
            f"[EXTRACTION] Complete: {successes}/{len(valid_triggers)} succeeded"
        )
        return aggregated

    except Exception as e:
        logger.error(f"[EXTRACTION] Orchestrator failed: {e}", exc_info=True)
        return {"success": False, "error": str(e)}

    finally:
        _extracting_games.discard(key)
