"""
LDVELH - Base Extractor
Template class for all specialized extractors.
Each extractor runs in its own DB transaction (independent failure).
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

    async def run(self, trigger_cycle: int) -> dict:
        """Template method: load checkpoint -> load messages -> build prompt -> LLM -> populate."""
        t0 = time.perf_counter()
        et = self.extraction_type

        try:
            async with self.pool.acquire() as conn:
                # 1. Read checkpoint
                from_cycle = await self.reader.get_extraction_checkpoint(
                    conn, et
                )

                # 2. Load unextracted messages
                messages = await self.reader.get_unextracted_messages(
                    conn, from_cycle, trigger_cycle
                )
                if not messages:
                    logger.info(
                        f"[{et.upper()}] No messages to extract "
                        f"(cycles {from_cycle+1}-{trigger_cycle})"
                    )
                    await self.populator.set_extraction_checkpoint(
                        conn, et, trigger_cycle
                    )
                    return {"type": et, "skipped": True}

                narrative_texts = [m["content"] for m in messages]

                # 3. Build domain-specific context
                context = await self._build_context(conn, messages)

                # 4. Build prompts
                system_prompt, user_prompt = self._build_prompts(
                    context, narrative_texts, trigger_cycle
                )

                # 5. Get tool schema
                schema = self._get_tool_schema()

            # 6. Call LLM (outside connection — may take a while)
            raw_result, call_cost = await self._call_llm(system_prompt, user_prompt, schema)
            if not raw_result:
                logger.warning(f"[{et.upper()}] LLM returned empty result")
                return {"type": et, "success": False, "error": "empty_response"}

            # 7. Populate DB (new connection + transaction)
            async with self.pool.acquire() as conn:
                async with conn.transaction():
                    await self.populator.load_registry(conn)
                    stats = await self._populate(conn, raw_result, trigger_cycle)

                    # 8. Update checkpoint
                    await self.populator.set_extraction_checkpoint(
                        conn, et, trigger_cycle
                    )

                    # 9. Log extraction
                    await self.populator.log_extraction(
                        conn, trigger_cycle, stats
                    )

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
        self, conn: Connection, messages: list[dict]
    ) -> dict:
        """Load domain-specific context from DB. Returns a dict used by _build_prompts."""

    @abstractmethod
    def _build_prompts(
        self, context: dict, narrative_texts: list[str], cycle: int
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
