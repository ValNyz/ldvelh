"""
LDVELH - Prompts Module
System prompts pour Claude
"""

from prompts.narrator_prompt import (
    NARRATOR_SYSTEM_PROMPT,
    build_narrator_context_prompt,
)
from prompts.world_generation_prompt import (
    get_full_generation_prompt,
    WORLD_GENERATION_SYSTEM_PROMPT,
)
from prompts.extractor_prompts import (
    # Résumé
    SUMMARY_SYSTEM,
    build_summary_prompt,
    # État protagoniste
    PROTAGONIST_STATE_SYSTEM,
    build_protagonist_state_prompt,
    # Entités
    ENTITIES_SYSTEM,
    build_entities_prompt,
    # Objets acquis
    OBJECTS_SYSTEM,
    build_objects_prompt,
    # Faits
    FACTS_SYSTEM,
    build_facts_prompt,
    # Relations
    RELATIONS_SYSTEM,
    build_relations_prompt,
    # Engagements
    COMMITMENTS_SYSTEM,
    build_commitments_prompt,
    # Helpers
    should_run_extraction,
    get_minimal_extraction,
    extract_object_hints,
)

__all__ = [
    # Narrateur
    "NARRATOR_SYSTEM_PROMPT",
    "build_narrator_context_prompt",
    # World Generation
    "WORLD_GENERATION_SYSTEM_PROMPT",
    "get_full_generation_prompt",
    # Extracteurs
    "SUMMARY_SYSTEM",
    "build_summary_prompt",
    "PROTAGONIST_STATE_SYSTEM",
    "build_protagonist_state_prompt",
    "ENTITIES_SYSTEM",
    "build_entities_prompt",
    "OBJECTS_SYSTEM",
    "build_objects_prompt",
    "FACTS_SYSTEM",
    "build_facts_prompt",
    "RELATIONS_SYSTEM",
    "build_relations_prompt",
    "COMMITMENTS_SYSTEM",
    "build_commitments_prompt",
    # Helpers
    "should_run_extraction",
    "get_minimal_extraction",
    "extract_object_hints",
]
