"""
LDVELH - Specialized Extraction Prompts
One prompt module per extraction type.
"""

from . import (
    characters_prompt,
    inventory_prompt,
    locations_prompt,
    narrative_arcs_prompt,
    organizations_prompt,
)

EXTRACTOR_MODULES = {
    "characters": characters_prompt,
    "locations": locations_prompt,
    "organizations": organizations_prompt,
    "inventory": inventory_prompt,
    "narrative_arcs": narrative_arcs_prompt,
}

__all__ = [
    "characters_prompt",
    "locations_prompt",
    "organizations_prompt",
    "inventory_prompt",
    "narrative_arcs_prompt",
    "EXTRACTOR_MODULES",
]
