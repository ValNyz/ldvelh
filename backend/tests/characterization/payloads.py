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
# Resolver reporting one genuinely new character: makes the orchestrator add the
# "characters" extractor, so extract_structured runs (mode-dependent code path).
NEW_CHARACTER_NAME = "Mira Kessler"
RESOLVER_NEW_CHARACTER = json.dumps({
    "existing": [],
    "new": [{
        "mentions": [NEW_CHARACTER_NAME],
        "suggested_name": NEW_CHARACTER_NAME,
        "entity_type": "character",
    }],
})
# Minimal valid schema.extraction.CharactersExtraction creating that character.
EXTRACT_CHARACTERS_NEW = {
    "entities_created": [{
        "entity_type": "character",
        "name": NEW_CHARACTER_NAME,
        "data": {"occupation": "Technicienne"},
    }],
}
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


# Shapes mirror what the wizard sends (frontend CharacterCreationStep.jsx):
# Fate aspects as {high_concept, trouble, other[]}, skills as {name: level},
# D6 attributes as {name: "3D+1"}, narrative traits as [{name, description}].
CHARACTER_DATA = {
    "narrative": {"name": "Ilya", "traits": [{"name": "Têtu", "description": "Ne lâche rien"}]},
    "fate_core": {
        "name": "Ilya",
        "aspects": {
            "high_concept": "Pilote déchu en quête de rédemption",
            "trouble": "Je dois de l'argent à tout le monde",
            "other": ["Mon vieux cargo est ma maison", "", ""],
        },
        "skills": {"Athlétisme": 4, "Pilotage": 3, "Empathie": 3,
                   "Combat": 2, "Discrétion": 2, "Volonté": 2,
                   "Contacts": 1, "Ressources": 1, "Physique": 1, "Tromperie": 1},
        "fate_points": 3,
        "refresh": 3,
    },
    "d6": {
        "name": "Ilya",
        "attributes": {"Dextérité": "3D", "Savoir": "2D+1", "Mécanique": "3D",
                       "Perception": "3D+1", "Vigueur": "2D+2", "Technique": "3D"},
    },
}


def narration_with_compel(base: str, result: str = "proposed") -> str:
    """Neutral narration plus a Fate compel proposal (schema/narration.py compel_* fields)."""
    data = json.loads(base)
    data["compel_aspect"] = "Je dois de l'argent à tout le monde"
    data["compel_result"] = result
    return json.dumps(data, ensure_ascii=False)


NARRATION_WITH_COMPEL = narration_with_compel(NARRATION)
