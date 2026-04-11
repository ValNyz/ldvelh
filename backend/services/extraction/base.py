"""
LDVELH - Base Extractor
Template class for all specialized extractors.
Per-message extraction: each extractor receives the message content
and narrator_deltas directly (no DB reload, no checkpoint system).
"""

from __future__ import annotations

import json
import logging
import time
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING
from uuid import UUID

from kg.reader import KnowledgeGraphReader
from kg.specialized_populator import ExtractionPopulator
from services.llm_service import get_llm_service

if TYPE_CHECKING:
    from asyncpg import Connection, Pool

    from .resolver import ResolutionMap

logger = logging.getLogger(__name__)


class BaseExtractor(ABC):
    """Base class for specialized extractors."""

    extraction_type: str  # "characters", "locations", etc.
    tool_name: str  # Tool name for LLM call
    tool_description: str  # Tool description for LLM call

    def __init__(
        self,
        pool: Pool,
        game_id: UUID,
        provider_name: str = "anthropic",
        api_key: str | None = None,
    ):
        self.pool = pool
        self.game_id = game_id
        self.provider_name = provider_name
        self.api_key = api_key
        self.reader = KnowledgeGraphReader(pool, game_id)
        self.populator = ExtractionPopulator(pool, game_id)

    async def run(
        self,
        message_content: str,
        narrator_deltas: dict,
        trigger_cycle: int,
        resolution_map: "ResolutionMap | None" = None,
    ) -> dict:
        """Extract entities from a single message."""
        t0 = time.perf_counter()
        et = self.extraction_type

        try:
            async with self.pool.acquire() as conn:
                # 1. Build domain-specific context
                context = await self._build_context(conn, narrator_deltas)

                # 2. Build prompts
                system_prompt, user_prompt = self._build_prompts(
                    context, message_content, trigger_cycle,
                    resolution_map=resolution_map,
                )

                # 3. Get tool schema
                schema = self._get_tool_schema()

            # 4. Call LLM (outside connection — may take a while)
            raw_result, call_cost = await self._call_llm(system_prompt, user_prompt, schema)
            if not raw_result:
                logger.warning(f"[{et.upper()}] LLM returned empty result")
                return {"type": et, "success": False, "error": "empty_response"}

            # 5. Populate DB (new connection + transaction)
            stats = {}
            async with self.pool.acquire() as conn:
                try:
                    async with conn.transaction():
                        await self.populator.load_registry(conn)
                        stats = await self._populate(conn, raw_result, trigger_cycle)
                except Exception as pop_err:
                    logger.warning(
                        f"[{et.upper()}] Populate failed (rolled back): {pop_err}"
                    )

                # Log extraction for auditing
                try:
                    await self.populator.log_extraction(
                        conn, trigger_cycle, stats
                    )
                except Exception as log_err:
                    logger.warning(f"[{et.upper()}] Log failed: {log_err}")

            elapsed = (time.perf_counter() - t0) * 1000
            logger.info(
                f"[{et.upper()}] Done in {elapsed:.0f}ms: "
                f"{json.dumps(stats, default=str)}"
            )
            return {
                "type": et, "success": True, "stats": stats,
                "ms": int(elapsed), "cost": call_cost,
            }

        except Exception as e:
            logger.error(f"[{et.upper()}] Extraction failed: {e}", exc_info=True)
            return {"type": et, "success": False, "error": str(e)}

    async def _call_llm(
        self, system_prompt: str, user_prompt: str, schema: dict
    ) -> tuple[dict | None, dict | None]:
        """Call the LLM service for structured extraction. Returns (result, cost)."""
        llm = get_llm_service()
        result = await llm.extract_structured(
            system_prompt=system_prompt,
            user_message=user_prompt,
            tool_name=self.tool_name,
            tool_description=self.tool_description,
            schema=schema,
            provider_name=self.provider_name,
            api_key=self.api_key,
        )
        cost = getattr(llm, "_last_call_cost", None)
        return result, cost

    @abstractmethod
    async def _build_context(
        self, conn: Connection, narrator_deltas: dict
    ) -> dict:
        """Load domain-specific context from DB. Returns a dict used by _build_prompts."""

    @abstractmethod
    def _build_prompts(
        self, context: dict, narrative_text: str, cycle: int,
        resolution_map: "ResolutionMap | None" = None,
    ) -> tuple[str, str]:
        """Return (system_prompt, user_prompt)."""

    @abstractmethod
    def _get_tool_schema(self) -> dict:
        """Return the JSON schema for the extraction output."""

    @abstractmethod
    async def _populate(
        self, conn: Connection, raw_result: dict, cycle: int
    ) -> dict:
        """Validate and populate DB from raw LLM result. Returns stats dict."""
