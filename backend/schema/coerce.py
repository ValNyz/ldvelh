"""Soft normalizers for LLM shape mistakes: a collection sent as another shape (dict for
list, list of pairs for dict, JSON string, null) is coerced at the schema boundary."""

import json
import logging
from typing import Any

from pydantic import ValidationInfo

logger = logging.getLogger(__name__)


def coerce_json_list(v: Any, info: ValidationInfo | None = None) -> list:
    """Coerce LLM output to a list. Handles common shape mistakes.

    - None → []
    - list → as-is
    - JSON string → parsed (if it's a list)
    - dict → list of values (LLMs often nest a labeled dict)
    - other scalar → [v]
    """
    if v is None or v == "":
        return []
    if isinstance(v, list):
        return v
    if isinstance(v, str):
        try:
            parsed = json.loads(v)
            if isinstance(parsed, list):
                return parsed
            if isinstance(parsed, dict):
                return list(parsed.values())
        except (json.JSONDecodeError, TypeError):
            pass
        return [v]
    if isinstance(v, dict):
        field = info.field_name if info else "?"
        logger.info(
            f"[Coerce] {field}: dict -> list (took values), keys were {list(v.keys())[:5]}"
        )
        return list(v.values())
    return [v]


def coerce_json_dict(v: Any, info: ValidationInfo | None = None) -> dict:
    """Coerce LLM output to a dict. Handles common shape mistakes.

    - None → {}
    - dict → as-is
    - JSON string → parsed (if it's a dict)
    - list of dicts with name/value → merged dict
    """
    if v is None or v == "":
        return {}
    if isinstance(v, dict):
        return v
    if isinstance(v, str):
        try:
            parsed = json.loads(v)
            if isinstance(parsed, dict):
                return parsed
        except (json.JSONDecodeError, TypeError):
            pass
        return {}
    if isinstance(v, list):
        # Heuristic: list of {name, value} pairs → merge into dict
        result = {}
        for item in v:
            if isinstance(item, dict):
                if "name" in item and "value" in item:
                    result[item["name"]] = item["value"]
                elif "name" in item and "level" in item:
                    result[item["name"]] = item["level"]
                else:
                    result.update(item)
            elif isinstance(item, str):
                result[item] = True
        field = info.field_name if info else "?"
        logger.info(f"[Coerce] {field}: list -> dict (merged {len(v)} items)")
        return result
    return {}
