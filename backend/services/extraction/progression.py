"""
LDVELH - Progression Extractor
Engine-specific character progression: traits, milestones, skill upgrades.
Delegates all engine-specific logic to the engine classes (Strategy pattern).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from services.engine import get_engine

from .base import BaseExtractor

if TYPE_CHECKING:
    from asyncpg import Connection

logger = logging.getLogger(__name__)


class ProgressionExtractor(BaseExtractor):
    extraction_type = "progression"
    tool_name = "extract_progression"
    tool_description = "Extract character progression from narrative text"

    async def run(self, trigger_cycle: int) -> dict:
        """Override run() to short-circuit for engines without progression."""
        async with self.pool.acquire() as conn:
            engine_type = await self.reader.get_engine_type(conn)

        engine = get_engine(engine_type)
        system_prompt = engine.get_progression_system_prompt()

        if not system_prompt:
            logger.info(
                f"[PROGRESSION] Skipped: engine '{engine_type}' has no progression"
            )
            # Still advance the checkpoint
            async with self.pool.acquire() as conn:
                await self.populator.set_extraction_checkpoint(
                    conn, self.extraction_type, trigger_cycle
                )
            return {"type": self.extraction_type, "skipped": True}

        # Store engine for use by template methods
        self._engine = engine
        self._engine_type = engine_type

        # Delegate to BaseExtractor template
        return await super().run(trigger_cycle)

    async def _build_context(
        self, conn: Connection, messages: list[dict]
    ) -> dict:
        stats = await self._engine.get_stats(conn, self.game_id)
        rolls = await self.reader.get_mechanic_rolls(conn, limit=10)

        # Build narrative summary from recent messages
        narrative_parts = []
        for m in messages:
            content = m.get("content", "")
            if content:
                # Take first 500 chars of each message
                narrative_parts.append(content[:500])
        narrative_summary = "\n---\n".join(narrative_parts) if narrative_parts else ""

        return {
            "stats": stats,
            "rolls": rolls,
            "narrative_summary": narrative_summary,
        }

    def _build_prompts(
        self, context: dict, narrative_texts: list[str], cycle: int
    ) -> tuple[str, str]:
        system_prompt = self._engine.get_progression_system_prompt()
        user_prompt = self._engine.build_progression_user_prompt(
            stats=context["stats"],
            rolls=context["rolls"],
            narrative_summary=context["narrative_summary"],
        )
        return system_prompt, user_prompt

    def _get_tool_schema(self) -> dict:
        return self._engine.get_progression_tool_schema()

    async def _populate(
        self, conn: Connection, raw_result: dict, cycle: int
    ) -> dict:
        try:
            changes = await self._engine.apply_progression(
                conn, self.game_id, raw_result
            )
        except Exception as e:
            logger.error(f"[PROGRESSION] apply_progression failed: {e}")
            changes = {"error": str(e)}

        stats = {
            "engine": self._engine_type,
            "changes": changes,
        }
        return stats
