"""
LDVELH - Characters Extractor Prompt
Handles character CRUD, ambient updates, skills, and character-related facts.
"""

from schema import PROTAGONIST_REF
from schema.extraction import CharactersExtraction

from .shared import CORE_RULES, ENTITY_REFERENCE_RULE, FACT_RULES, STRICT_KEYS_RULE

SYSTEM_PROMPT = f"""Tu es l'extracteur de PERSONNAGES d'un jeu de rôle narratif.
Tu analyses les textes narratifs et extrais les changements relatifs aux personnages (PNJ).

## FORMAT DE SORTIE

```json
{{
    "proposed_entities": [
        {{
            "entity_type": "character",
            "label": "<name, or what the protagonist sees, as the text gives it>",
            "kind": "proper_name",
            "known_by_protagonist": true,
            "descriptor": null,
            "fields": {{
                "description": "<physical description>",
                "mood": "<mood>",
                "origin": "<origin>",
                "species": "human",
                "gender": "<gender>",
                "pronouns": "<pronouns>",
                "occupation": "<occupation>",
                "traits": ["<trait>"],
                "romantic_potential": false,
                "workplace_ref": "E4",
                "residence_ref": null
            }}
        }}
    ],
    "entities_updated": [
        {{
            "entity_ref": "E12",
            "entity_type": "character",
            "now_known": true,
            "real_name": "<the name the protagonist just learned>",
            "changes": {{
                "mood": "<new mood>",
                "occupation": "<occupation>"
            }}
        }}
    ],
    "entities_removed": [
        {{
            "entity_ref": "E12",
            "reason": "<why the character left the story for good>",
            "cycle": 5
        }}
    ],
    "ambient_updates": [
        {{
            "entity_ref": "E12",
            "entity_type": "character",
            "ambient": "<what an observer notices about the character right now>"
        }}
    ],
    "skills_changed": [
        {{"name": "négociation", "level": 2}}
    ],
    "facts": [
        {{
            "fact_type": "revelation",
            "description": "<what the character revealed>",
            "semantic_key": "<subject>:<verb>:<object>",
            "importance": 4,
            "participants": [
                {{"entity_ref": "E12", "role": "actor"}},
                {{"entity_ref": "{PROTAGONIST_REF}", "role": "witness"}}
            ]
        }}
    ]
}}
```

## CHARACTER DATA FIELDS

fields (for proposed_entities):
- description (string), mood (string), age (string), origin (string)
- species (string, default "human"), gender (string), pronouns (string)
- occupation (string), traits (list of strings)
- romantic_potential (bool), workplace_ref (string), residence_ref (string)

changes (for entities_updated): same keys as fields above.

## AMBIENT UPDATES

For each character involved in an active arc, generate an ambient text (max 200 chars)
describing the VISIBLE effect: behavior, appearance, mood shift.
Only include if the arc visibly affects the character this cycle.

## SKILLS

Only extract protagonist skill changes (new skills learned or level-ups).

{STRICT_KEYS_RULE}

{ENTITY_REFERENCE_RULE}

{FACT_RULES}

{CORE_RULES}

## CHARACTER-SPECIFIC RULES

1. Only propose entities with entity_type="character"
2. A character of the ENTITIES IN THIS SCENE list is updated by its handle, never proposed again.
3. For unknown characters (protagonist hasn't learned their name): kind="descriptor", label = a SIMPLE PHYSICAL description of what the protagonist SEES, never a poetic title nor a narrative role.
4. entities_removed: only for permanent departures (death, left for good) — NOT temporary absence
5. Extract only CHARACTER-related facts (interactions, revelations about people)
6. Ambient: what an observer would NOTICE about this character right now"""


def build_user_prompt(
    narrative_text: str,
    cycle: int,
    known_characters: list[dict],
    active_arcs_with_characters: list[dict] | None = None,
) -> str:
    """Build the user prompt for the characters extractor."""
    texts_joined = narrative_text

    chars_lines = []
    for c in known_characters[:50]:
        name = c.get("name", "?")
        descriptor = c.get("descriptor")
        occ = c.get("occupation", "")
        known = c.get("known_by_protagonist", True)
        mood = c.get("mood", "")
        ambient = c.get("ambient", "")
        line = f"- {name}"
        if descriptor:
            line += f' (alias: "{descriptor}")'
        if occ:
            line += f" ({occ})"
        if not known:
            line += " [unknown to protagonist]"
        if mood:
            line += f" — mood: {mood}"
        if ambient:
            line += f" — ambient: {ambient}"
        chars_lines.append(line)
    chars_str = "\n".join(chars_lines) if chars_lines else "None"

    arcs_section = ""
    if active_arcs_with_characters:
        arcs_lines = []
        for arc in active_arcs_with_characters:
            parts = ", ".join(arc.get("participants", [])) or "none"
            arcs_lines.append(
                f"- {arc['title']} [{arc.get('domain', '?')}] "
                f"(intensity {arc.get('intensity', '?')}/5): {parts}"
            )
        arcs_section = "\n\nActive arcs involving characters (for ambient_updates):\n" + "\n".join(arcs_lines)

    return f"""## CONTEXT
- Cycle: {cycle}
- Known characters:
{chars_str}
{arcs_section}

## NARRATIVE TEXTS

{texts_joined}

## INSTRUCTIONS
1. Propose NEW characters absent from the scene list (proposed_entities)
2. Extract updates to EXISTING characters (mood, occupation, etc.)
3. Extract character removals (permanent departures only)
4. Generate ambient_updates for characters affected by active arcs
5. Extract protagonist skill changes if any
6. Extract character-related facts

JSON:"""


def get_tool_schema() -> dict:
    """Return JSON schema for CharactersExtraction."""
    return CharactersExtraction.model_json_schema()
