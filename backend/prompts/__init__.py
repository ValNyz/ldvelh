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
    BATCH_EXTRACTION_SYSTEM,
    build_batch_extraction_prompt,
    should_run_extraction,
    extract_object_hints,
)

__all__ = [
    # Narrator
    "NARRATOR_SYSTEM_PROMPT",
    "build_narrator_context_prompt",
    # World Generation
    "WORLD_GENERATION_SYSTEM_PROMPT",
    "get_full_generation_prompt",
    # Batch extraction
    "BATCH_EXTRACTION_SYSTEM",
    "build_batch_extraction_prompt",
    # Helpers
    "should_run_extraction",
    "extract_object_hints",
]
