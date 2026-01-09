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

__all__ = [
    "NARRATOR_SYSTEM_PROMPT",
    "build_narrator_context_prompt",
    "WORLD_GENERATION_SYSTEM_PROMPT",
    "get_full_generation_prompt",
]
