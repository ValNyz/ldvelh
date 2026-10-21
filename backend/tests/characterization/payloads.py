"""Scripted LLM payloads reused across characterization scenarios.

World and narration payloads are FROZEN copies under fixtures/ (taken from
tests/prompt_examples.py), so reworking the prompt examples does not churn snapshots.
test_harness_smoke validates them against the current Pydantic schemas, so schema
drift still shows up there.
"""

import json
import re
from pathlib import Path

_FIXTURES = Path(__file__).parent / "fixtures"

WORLD_GEN = (_FIXTURES / "world_gen.json").read_text(encoding="utf-8")
NARRATION = (_FIXTURES / "narration.json").read_text(encoding="utf-8")
# Minimal VALID shapes: keys must match the identity decision output (services.identity.
# decision.parse) and schema.director.DirectorOutput (the smoke test checks both).
IDENTITY_EMPTY = json.dumps({"mentions": []})
# A narration naming one genuinely new character, and the identity decision creating her:
# the identity service creates the stub, which makes the orchestrator add the "characters"
# extractor, so LLMSession.extract_structured runs (mode-dependent code path).
NEW_CHARACTER_NAME = "Mira Kessler"
NEW_CHARACTER_TEXT = (
    json.loads(NARRATION)["narrative_text"]
    + f"\n\n{NEW_CHARACTER_NAME} répare un panneau près de l'entrée."
)
NARRATION_NEW_CHARACTER = json.dumps(
    {**json.loads(NARRATION), "narrative_text": NEW_CHARACTER_TEXT}, ensure_ascii=False
)
IDENTITY_NEW_CHARACTER = json.dumps({
    "mentions": [{
        "surface": NEW_CHARACTER_NAME,
        "before": "",
        "decision": "NEW",
        "handle": None,
        "new_type": "character",
        "new_kind": "proper_name",
        "evidence": "a person the scene introduces",
    }],
})
_SCENE_LINE = re.compile(r"^- (E\d+) · (\w+) · (.+?) · ", re.MULTILINE)


def scene_handle(prompt: str, label: str) -> str:
    """The handle the ENTITIES IN THIS SCENE section of an extraction prompt gives
    `label` (the label itself when the section does not list it)."""
    for handle, _, line_label in _SCENE_LINE.findall(prompt):
        if line_label == label:
            return handle
    return label


def extract_characters_new(prompt: str) -> dict:
    """Valid schema.extraction.CharactersExtraction enriching the new character, by the
    handle the prompt lists for her (a scripted payload computed from the prompt)."""
    return {
        "entities_updated": [{
            "entity_ref": scene_handle(prompt, NEW_CHARACTER_NAME),
            "entity_type": "character",
            "changes": {"occupation": "Technicienne"},
        }],
    }


# Valid schema.extraction.CharactersExtraction proposing the new character (an extractor
# that met her outside the scene list): the identity service creates her.
EXTRACT_CHARACTERS_PROPOSED = {
    "proposed_entities": [{
        "entity_type": "character",
        "label": NEW_CHARACTER_NAME,
        "kind": "proper_name",
        "fields": {"occupation": "Technicienne"},
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
