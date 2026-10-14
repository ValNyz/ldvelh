"""Scripted LLM payloads reused across characterization scenarios.

World and narration payloads come from prompts/examples.py, the single source of
truth for JSON examples, so they match the schemas the app validates against.
"""

import json

from prompts.examples import NARRATION_EXAMPLE_NEUTRAL, WORLD_GENERATION_EXAMPLE

WORLD_GEN = WORLD_GENERATION_EXAMPLE
# NARRATION_EXAMPLE_NEUTRAL is a dict; stream() yields text, so serialize it.
NARRATION = json.dumps(NARRATION_EXAMPLE_NEUTRAL, ensure_ascii=False)
# Minimal VALID shapes: keys must match schema.extraction.EntityResolution and
# schema.director.DirectorOutput (the smoke test model_validate()s both).
RESOLVER_EMPTY = json.dumps({"existing": [], "new": []})
DIRECTOR = json.dumps({
    "tension_level": 3,
    "narrator_guidance": "Rythme calme, laisser le joueur explorer.",
    "planned_events": [],
    "arc_updates": [],
    "long_term_vision": "Rien de particulier.",
})


def mechanical(requires_test: bool, skill: str = "Athlétisme", skill_value: int = 2,
               difficulty: int = 2) -> str:
    """MechanicalDecision JSON (schema/engine.py:183)."""
    if not requires_test:
        return json.dumps({"requires_test": False, "reason": "Action triviale."})
    return json.dumps({
        "requires_test": True,
        "skill": skill,
        "skill_value": skill_value,
        "difficulty": difficulty,
        "difficulty_label": "Correct",
        "reason": "Action risquée.",
    })
