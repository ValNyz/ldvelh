"""
LDVELH - Inventory Extractor
Handles object creation with canonical_name dedup, inventory changes, and facts.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from prompts.extractions import inventory_prompt
from schema import FactData
from schema.extraction import InventoryChange, ObjectCreation

from .base import BaseExtractor

if TYPE_CHECKING:
    from asyncpg import Connection

logger = logging.getLogger(__name__)


class InventoryExtractor(BaseExtractor):
    extraction_type = "inventory"
    tool_name = "extract_inventory"
    tool_description = "Extract inventory changes from narrative text"

    async def _build_context(self, conn: Connection, messages: list[dict]) -> dict:
        canonical_names = await self.reader.get_object_canonical_names(conn)
        objects = await self.reader.get_objects(conn)

        # Collect inventory_hints from narrator_deltas
        inventory_hints = []
        for m in messages:
            deltas = m.get("narrator_deltas")
            if deltas and isinstance(deltas, dict):
                inventory_hints.extend(deltas.get("inventory_hints", []))

        return {
            "canonical_names": canonical_names,
            "objects": objects,
            "inventory_hints": inventory_hints,
        }

    def _build_prompts(
        self, context: dict, narrative_texts: list[str], cycle: int
    ) -> tuple[str, str]:
        known_objs = [
            {"name": o["name"], "category": o.get("category", "misc")}
            for o in context["objects"]
        ]
        user_prompt = inventory_prompt.build_user_prompt(
            narrative_texts=narrative_texts,
            cycle=cycle,
            existing_canonical_names=context["canonical_names"],
            inventory_hints=context.get("inventory_hints") or None,
            known_objects=known_objs or None,
        )
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
