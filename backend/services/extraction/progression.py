"""
LDVELH - Progression Extractor
Engine-specific character progression: traits, milestones, skill upgrades.
Delegates all engine-specific logic to the engine classes (Strategy pattern).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from uuid import UUID

from services.engine import get_engine

from .base import BaseExtractor

if TYPE_CHECKING:
    from asyncpg import Connection

    from domain.identity import SceneEntity

logger = logging.getLogger(__name__)


class ProgressionExtractor(BaseExtractor):
    extraction_type = "progression"
    tool_name = "extract_progression"
    tool_description = "Extract character progression from narrative text"
    writes_entity_refs = False  # engine stats only

    async def run(self, message_content: str, narrator_deltas: dict, trigger_cycle: int,
                  scene_entities: list[SceneEntity] | None = None, *,
                  source_message_id: UUID | None = None,
                  turn_id: UUID | None = None) -> dict:
        """Override run() to short-circuit for engines without progression."""
        async with self.pool.acquire() as conn:
            engine_type = await self.reader.get_engine_type(conn)

        engine = get_engine(engine_type)
        system_prompt = engine.get_progression_system_prompt()

        if not system_prompt:
            logger.info(
                f"[PROGRESSION] Skipped: engine '{engine_type}' has no progression"
            )
            return {"type": self.extraction_type, "skipped": True}

        # Store engine for use by template methods
        self._engine = engine
        self._engine_type = engine_type

        # Delegate to BaseExtractor template
        return await super().run(message_content, narrator_deltas, trigger_cycle,
                                 scene_entities, source_message_id=source_message_id,
                                 turn_id=turn_id)

    async def _build_context(
        self, conn: Connection, narrator_deltas: dict
    ) -> dict:
        stats = await self._engine.get_stats(conn, self.game_id)
        rolls = await self.reader.get_mechanic_rolls(conn, limit=10)

        return {
            "stats": stats,
            "rolls": rolls,
        }

    def _build_prompts(
        self, context: dict, narrative_text: str, cycle: int
    ) -> tuple[str, str]:
        system_prompt = self._engine.get_progression_system_prompt()
        user_prompt = self._engine.build_progression_user_prompt(
            stats=context["stats"],
            rolls=context["rolls"],
            narrative_summary=narrative_text,
        )
        return system_prompt, user_prompt

    def _get_tool_schema(self) -> dict:
        return self._engine.get_progression_tool_schema()

    async def _populate(
        self, conn: Connection, raw_result: dict, cycle: int
    ) -> dict:
        stats = {"engine": self._engine_type, "changes": {}, "errors": []}
        changes = await self._write_item(
            conn, stats, "progression",
            lambda: self._engine.apply_progression(conn, self.game_id, raw_result),
        )
        stats["changes"] = changes or {}
        return stats
