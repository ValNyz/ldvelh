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
from collections.abc import Awaitable, Callable, Iterable
from typing import TYPE_CHECKING, Any
from uuid import UUID

from kg.item_writes import write_item, write_items
from kg.reader import KnowledgeGraphReader
from kg.specialized_populator import ExtractionPopulator
from config import get_settings
from prompts.extraction.shared import protagonist_section
from schema import EntityType, FactData
from schema.extraction import AmbientUpdate, EntityCreation, EntityUpdate
from utils.log_safe import log_cause, log_exception, safe_text

if TYPE_CHECKING:
    from asyncpg import Connection, Pool

    from llm.session import LLMSession

    from .resolver import ResolutionMap

logger = logging.getLogger(__name__)


class BaseExtractor(ABC):
    """Base class for specialized extractors."""

    extraction_type: str  # "characters", "locations", etc.
    tool_name: str  # Tool name for LLM call
    tool_description: str  # Tool description for LLM call
    writes_entity_refs = True  # its output references entities: name the PC in the prompt

    def __init__(self, pool: Pool, game_id: UUID, session: "LLMSession"):
        self.pool = pool
        self.game_id = game_id
        self.session = session
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
        call_cost = None  # returned on every exit once the LLM was called (it was billed)

        try:
            async with self.pool.acquire() as conn:
                # 1. Build domain-specific context
                context = await self._build_context(conn, narrator_deltas)

                # 2. Build prompts
                system_prompt, user_prompt = self._build_prompts(
                    context, message_content, trigger_cycle,
                    resolution_map=resolution_map,
                )
                if self.writes_entity_refs:
                    user_prompt += protagonist_section(
                        await self.reader.get_protagonist_name(conn))

                # 3. Get tool schema
                schema = self._get_tool_schema()

            # 4. Call LLM (outside connection — may take a while)
            raw_result, call_cost = await self._call_llm(system_prompt, user_prompt, schema)
            if not raw_result:
                logger.warning(f"[{et.upper()}] LLM returned empty result")
                return {"type": et, "success": False, "error": "empty_response",
                        "cost": call_cost}

            # 5. Populate DB (new connection + transaction, one savepoint per item)
            stats, populate_error = await self._populate_committed(raw_result, trigger_cycle)
            elapsed = (time.perf_counter() - t0) * 1000
            result = {"type": et, "stats": stats, "ms": int(elapsed), "cost": call_cost}
            if populate_error:
                return {**result, "success": False, "error": "populate_failed"}
            errors = stats.get("errors")
            logger.info(
                f"[{et.upper()}] Done in {elapsed:.0f}ms"
                f"{' (partial)' if errors else ''}: {json.dumps(stats, default=str)}"
            )
            # Some items failed: what was committed is kept, but the run is not a success.
            return {**result, "success": not errors, **({"partial": True} if errors else {})}

        except Exception as e:
            log_exception(logger, logging.ERROR, f"[{et.upper()}] Extraction failed", e,
                          debug_detail=get_settings().log_prompts)
            return {"type": et, "success": False, "error": safe_text(e), "cost": call_cost}

    async def _populate_committed(
        self, raw_result: dict, cycle: int
    ) -> tuple[dict, str | None]:
        """Run `_populate` in one transaction and log the outcome to extraction_logs.

        Returns (stats, error). On error the whole transaction was rolled back: stats then
        only carry that error, since none of the counted writes were committed.
        """
        et = self.extraction_type.upper()
        stats: dict = {}
        error = None
        async with self.pool.acquire() as conn:
            try:
                async with conn.transaction():
                    await self.populator.load_registry(conn)
                    stats = await self._populate(conn, raw_result, cycle)
            except Exception as pop_err:
                error = f"populate: {safe_text(pop_err)}"
                stats = {"errors": [error]}
                log_cause(logger, logging.WARNING, f"[{et}] Populate failed (rolled back)",
                          pop_err, debug_detail=get_settings().log_prompts)

            # Log extraction for auditing
            try:
                await self.populator.log_extraction(conn, cycle, stats)
            except Exception as log_err:
                log_cause(logger, logging.WARNING, f"[{et}] Log failed", log_err,
                          debug_detail=get_settings().log_prompts)
        return stats, error

    async def _write_item(
        self, conn: Connection, stats: dict, label: str,
        write: Callable[[], Awaitable[Any]],
    ) -> Any:
        """One item in its own SAVEPOINT (see kg.item_writes.write_item)."""
        return await write_item(conn, stats["errors"], label, write, self._log_prefix)

    async def _write_items(
        self, conn: Connection, stats: dict, label: str, items: Iterable | None,
        write: Callable[[Any], Awaitable[Any]], counter: str | None = None,
    ) -> None:
        """`_write_item` for each item; a truthy write(item) result increments stats[counter]."""
        await write_items(conn, stats, label, items, write, counter, self._log_prefix)

    @property
    def _log_prefix(self) -> str:
        return f"[{self.extraction_type.upper()}] "

    async def _write_facts(
        self, conn: Connection, stats: dict, raw_result: dict, cycle: int
    ) -> None:
        """Create the extracted facts, counted in stats["facts_created"]."""
        async def create(fact_data: dict):
            fact_data.setdefault("cycle", cycle)
            return await self.populator.create_fact(conn, FactData.model_validate(fact_data))

        await self._write_items(conn, stats, "fact", raw_result.get("facts"), create,
                                "facts_created")

    async def _write_entities(
        self, conn: Connection, stats: dict, raw_result: dict, cycle: int,
        entity_type: EntityType,
    ) -> None:
        """Entity creations, updates and ambient updates of one entity type."""
        await self._write_items(conn, stats, "create", raw_result.get("entities_created"),
                                lambda d: self._create_entity(conn, d, cycle, entity_type),
                                "entities_created")
        # Reload registry after new entities
        if stats["entities_created"]:
            await self.populator.load_registry(conn)
        await self._write_items(conn, stats, "update", raw_result.get("entities_updated"),
                                lambda d: self._update_entity(conn, d, cycle, entity_type),
                                "entities_updated")
        await self._write_items(conn, stats, "ambient", raw_result.get("ambient_updates"),
                                lambda d: self._update_ambient(conn, d, entity_type),
                                "ambients_updated")

    def _skip_creation(self, ec: EntityCreation) -> bool:
        """Hook: True to ignore an extracted creation."""
        return False

    async def _create_entity(
        self, conn: Connection, ec_data: dict, cycle: int, entity_type: EntityType
    ) -> bool:
        ec_data.setdefault("entity_type", entity_type.value)
        ec = EntityCreation.model_validate(ec_data)
        if ec.entity_type != entity_type or self._skip_creation(ec):
            return False
        return await self.populator._process_entity_creation(conn, ec, cycle)

    async def _update_entity(
        self, conn: Connection, eu_data: dict, cycle: int, entity_type: EntityType
    ) -> bool:
        eu_data.setdefault("entity_type", entity_type.value)
        await self.populator._process_entity_update(
            conn, EntityUpdate.model_validate(eu_data), cycle)
        return True

    async def _update_ambient(
        self, conn: Connection, amb_data: dict, entity_type: EntityType
    ) -> bool:
        amb_data.setdefault("entity_type", entity_type.value)
        amb = AmbientUpdate.model_validate(amb_data)
        return await self.populator.update_entity(
            conn, amb.entity_type, amb.entity_ref, {"ambient": amb.ambient}
        )

    async def _call_llm(
        self, system_prompt: str, user_prompt: str, schema: dict
    ) -> tuple[dict | None, dict | None]:
        """Structured extraction through the session. Returns (result, this call's cost)."""
        settings = get_settings()
        call = await self.session.extract_structured(
            system_prompt=system_prompt,
            user_message=user_prompt,
            tool_name=self.tool_name,
            tool_description=self.tool_description,
            schema=schema,
            temperature=settings.temperature_extraction,
            max_tokens=settings.max_tokens_extraction,
        )
        return call.value, call.cost

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
