"""
LDVELH - Utilities Package
"""

from .json_utils import (
    parse_json_response,
    clean_json_string,
    try_repair_json,
    safe_json_dumps,
)

from .llm_output_normalizer import (
    # Fonctions principales de normalisation
    normalize_world_generation,
    normalize_narration_output,
    normalize_narrative_extraction,
    # Fonctions granulaires (si besoin)
    normalize_relation,
    normalize_entity,
    normalize_fact,
    normalize_arc,
    normalize_character,
    normalize_arrival_event,
    normalize_value,
)

__all__ = [
    # JSON
    "parse_json_response",
    "clean_json_string",
    "try_repair_json",
    "safe_json_dumps",
    # LLM Output Normalizer
    "normalize_world_generation",
    "normalize_narration_output",
    "normalize_narrative_extraction",
    "normalize_relation",
    "normalize_entity",
    "normalize_fact",
    "normalize_arc",
    "normalize_character",
    "normalize_arrival_event",
    "normalize_value",
]
