"""
LDVELH - Inventory Extractor
Handles object creation with canonical_name dedup, inventory changes, and facts.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from prompts.extraction import inventory_prompt
from schema import FactData
from schema.extraction import InventoryChange, ObjectCreation
from services.engine import get_engine

from .base import BaseExtractor

if TYPE_CHECKING:
    from asyncpg import Connection

logger = logging.getLogger(__name__)


class InventoryExtractor(BaseExtractor):
    extraction_type = "inventory"
    tool_name = "extract_inventory"
    tool_description = "Extract inventory changes from narrative text"

    async def _build_context(self, conn: Connection, narrator_deltas: dict) -> dict:
        canonical_names = await self.reader.get_object_canonical_names(conn)
        objects = await self.reader.get_objects(conn)

        # Load engine for object extensions
        engine_type = await self.reader.get_engine_type(conn)
        self._engine = get_engine(engine_type)
        self._engine_type = engine_type

        # Collect inventory_hints from narrator_deltas
        inventory_hints = narrator_deltas.get("inventory_hints", [])

        return {
            "canonical_names": canonical_names,
            "objects": objects,
            "inventory_hints": inventory_hints,
        }

    def _build_prompts(
        self, context: dict, narrative_text: str, cycle: int,
        resolution_map=None,
    ) -> tuple[str, str]:
        known_objs = [
            {"name": o["name"], "category": o.get("category", "misc")}
            for o in context["objects"]
        ]
        user_prompt = inventory_prompt.build_user_prompt(
            narrative_text=narrative_text,
            cycle=cycle,
            existing_canonical_names=context["canonical_names"],
            inventory_hints=context.get("inventory_hints") or None,
            known_objects=known_objs or None,
            engine_object_addon=self._engine.get_object_prompt_addon() or None,
        )
        if resolution_map:
            from prompts.extraction.shared import RESOLUTION_SECTION_HEADER
            section = resolution_map.to_prompt_section("object")
            if section:
                user_prompt += f"\n\n{RESOLUTION_SECTION_HEADER}{section}"
        return inventory_prompt.SYSTEM_PROMPT, user_prompt

    def _get_tool_schema(self) -> dict:
        return inventory_prompt.get_tool_schema()

    async def _populate(
        self, conn: Connection, raw_result: dict, cycle: int
    ) -> dict:
        stats = {"objects_created": 0, "inventory_changes": 0,
                 "facts_created": 0, "errors": []}

        # Objects created (with canonical dedup)
        for obj_data in raw_result.get("objects_created", []):
            try:
                # Ensure from_hint has a default
                obj_data.setdefault("from_hint", obj_data.get("name", ""))
                obj = ObjectCreation.model_validate(obj_data)
                result = await self.populator.create_object_with_canonical(
                    conn, obj, cycle
                )
                if result:
                    stats["objects_created"] += 1
                    # Create engine-specific extension if engine_data present
                    engine_data = obj.engine_data
                    if engine_data and self._engine_type != "none":
                        object_id = result if isinstance(result, type(self.game_id)) else None
                        if object_id:
                            try:
                                await self._engine.create_object_extension(
                                    conn, object_id, engine_data
                                )
                            except Exception as ext_err:
                                logger.warning(
                                    f"[INVENTORY] Engine extension failed: {ext_err}"
                                )
            except Exception as e:
                stats["errors"].append(f"object: {e}")

        # Inventory changes
        for ic_data in raw_result.get("inventory_changes", []):
            try:
                ic = InventoryChange.model_validate(ic_data)
                await self.populator._process_inventory_change(conn, ic, cycle)
                stats["inventory_changes"] += 1
            except Exception as e:
                stats["errors"].append(f"inv_change: {e}")

        # Facts
        for fact_data in raw_result.get("facts", []):
            try:
                fact_data.setdefault("cycle", cycle)
                fact = FactData.model_validate(fact_data)
                if await self.populator.create_fact(conn, fact):
                    stats["facts_created"] += 1
            except Exception as e:
                stats["errors"].append(f"fact: {e}")

        return stats
