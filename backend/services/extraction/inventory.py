"""
LDVELH - Inventory Extractor
Handles object creation deduplicated by label, inventory changes, and facts.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from prompts.extraction import inventory_prompt
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
        objects = await self.reader.get_objects(conn)

        # Load engine for object extensions
        engine_type = await self.reader.get_engine_type(conn)
        self._engine = get_engine(engine_type)
        self._engine_type = engine_type

        # Collect inventory_hints from narrator_deltas
        inventory_hints = narrator_deltas.get("inventory_hints", [])

        return {
            "objects": objects,
            "inventory_hints": inventory_hints,
        }

    def _build_prompts(
        self, context: dict, narrative_text: str, cycle: int
    ) -> tuple[str, str]:
        known_objs = [
            {"name": o["name"], "category": o.get("category", "misc")}
            for o in context["objects"]
        ]
        user_prompt = inventory_prompt.build_user_prompt(
            narrative_text=narrative_text,
            cycle=cycle,
            existing_labels=[o["name"] for o in context["objects"]],
            inventory_hints=context.get("inventory_hints") or None,
            known_objects=known_objs or None,
            engine_object_addon=self._engine.get_object_prompt_addon() or None,
        )
        return inventory_prompt.SYSTEM_PROMPT, user_prompt

    def _get_tool_schema(self) -> dict:
        return inventory_prompt.get_tool_schema()

    async def _populate(
        self, conn: Connection, raw_result: dict, cycle: int
    ) -> dict:
        stats = {"objects_created": 0, "inventory_changes": 0,
                 "facts_created": 0, "errors": []}
        await self._write_items(conn, stats, "object", raw_result.get("objects_created"),
                                lambda d: self._create_object(conn, stats, d, cycle),
                                "objects_created")
        await self._write_items(conn, stats, "inv_change", raw_result.get("inventory_changes"),
                                lambda d: self._change_inventory(conn, d, cycle),
                                "inventory_changes")
        await self._write_facts(conn, stats, raw_result, cycle)
        return stats

    async def _create_object(
        self, conn: Connection, stats: dict, obj_data: dict, cycle: int
    ) -> bool:
        """Create an object (deduplicated by label) and its engine extension."""
        obj_data.setdefault("from_hint", obj_data.get("name", ""))
        obj = ObjectCreation.model_validate(obj_data)
        result = await self.populator.create_object_by_label(conn, obj, cycle)
        if not result:
            return False
        engine_data = obj.engine_data
        object_id = result if isinstance(result, type(self.game_id)) else None
        if engine_data and self._engine_type != "none" and object_id:
            # Nested savepoint: a failed extension keeps the object.
            await self._write_item(
                conn, stats, "object_extension",
                lambda: self._engine.create_object_extension(conn, object_id, engine_data),
            )
        return True

    async def _change_inventory(self, conn: Connection, ic_data: dict, cycle: int) -> bool:
        ic = InventoryChange.model_validate(ic_data)
        await self.populator.process_inventory_change(conn, ic, cycle)
        return True
