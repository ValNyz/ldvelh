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

# Specialized extraction prompts (replaces old extractor_prompts)
from prompts.extraction import EXTRACTOR_MODULES

__all__ = [
    # Narrator
    "NARRATOR_SYSTEM_PROMPT",
    "build_narrator_context_prompt",
    # World Generation
    "WORLD_GENERATION_SYSTEM_PROMPT",
    "get_full_generation_prompt",
    # Extraction
    "EXTRACTOR_MODULES",
]
