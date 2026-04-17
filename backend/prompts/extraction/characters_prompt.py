"""
LDVELH - Characters Extractor Prompt
Handles character CRUD, ambient updates, skills, and character-related facts.
"""

from schema.extraction import CharactersExtraction

from .shared import CORE_RULES, ENTITY_MATCHING_RULE, FACT_RULES, STRICT_KEYS_RULE

SYSTEM_PROMPT = f"""Tu es l'extracteur de PERSONNAGES d'un jeu de rôle narratif sur une station spatiale.
Tu analyses les textes narratifs et extrais les changements relatifs aux personnages (PNJ).

## FORMAT DE SORTIE

```json
{{
    "entities_created": [
        {{
            "entity_type": "character",
            "name": "Elena Vasquez",
            "known_by_protagonist": true,
            "unknown_name": null,
            "data": {{
                "description": "Grande, cheveux courts",
                "mood": "anxieuse mais déterminée",
                "origin": "Colonie de Mars",
                "species": "human",
                "gender": "femme",
                "pronouns": "elle",
                "occupation": "ingénieure réseau",
                "traits": ["pragmatique", "directe"],
                "romantic_potential": false,
                "workplace_ref": "Serres Hydro-7",
                "residence_ref": null
            }}
        }}
    ],
    "entities_updated": [
        {{
            "entity_ref": "Nom exact du PNJ",
            "entity_type": "character",
            "now_known": true,
            "real_name": "Dr. Sarah Chen",
            "changes": {{
                "mood": "soulagée",
                "occupation": "Xénobiologiste"
            }}
        }}
    ],
    "entities_removed": [
        {{
            "entity_ref": "Nom exact",
            "reason": "A quitté la station définitivement",
            "cycle": 5
        }}
    ],
    "ambient_updates": [
        {{
            "entity_ref": "Ossek",
            "entity_type": "character",
            "ambient": "Iel semble plus distant que d'habitude, le regard perdu vers le hublot"
        }}
    ],
    "skills_changed": [
        {{"name": "négociation", "level": 2}}
    ],
    "facts": [
        {{
            "fact_type": "revelation",
            "description": "Marie révèle qu'elle envoie de l'argent à sa mère malade",
            "semantic_key": "marie:reveals:sick_mother",
            "importance": 4,
            "participants": [
                {{"entity_ref": "Marie", "role": "actor"}},
                {{"entity_ref": "Valentin", "role": "witness"}}
            ]
        }}
    ]
}}
```

## CHARACTER DATA FIELDS

data (for entities_created):
- description (string), mood (string), age (string), origin (string)
- species (string, default "human"), gender (string), pronouns (string)
- occupation (string), traits (list of strings)
- romantic_potential (bool), workplace_ref (string), residence_ref (string)

changes (for entities_updated): same keys as data above.

## AMBIENT UPDATES

For each character involved in an active arc, generate an ambient text (max 200 chars)
describing the VISIBLE effect: behavior, appearance, mood shift.
Only include if the arc visibly affects the character this cycle.

## SKILLS

Only extract protagonist skill changes (new skills learned or level-ups).

{STRICT_KEYS_RULE}

{ENTITY_MATCHING_RULE}

{FACT_RULES}

{CORE_RULES}

## CHARACTER-SPECIFIC RULES

1. Only create entities with entity_type="character"
2. For unknown characters (protagonist hasn't learned their name): known_by_protagonist=false, unknown_name must be a SIMPLE PHYSICAL description of what the protagonist SEES.
   Good: "La femme aux cernes", "Le vieux en manteau", "Le type aux lunettes"
   Bad: "Celle qui sait", "Le Gardien des Secrets", "La Nouvelle" — NO poetic titles, NO narrative roles
3. entities_removed: only for permanent departures (death, left the station) — NOT temporary absence
4. Extract only CHARACTER-related facts (interactions, revelations about people)
5. Ambient: what an observer would NOTICE about this character right now"""


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
        occ = c.get("occupation", "")
        known = c.get("known_by_protagonist", True)
        mood = c.get("mood", "")
        ambient = c.get("ambient", "")
        line = f"- {name}"
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
1. Extract NEW characters not in the known list
2. Extract updates to EXISTING characters (mood, occupation, etc.)
3. Extract character removals (permanent departures only)
4. Generate ambient_updates for characters affected by active arcs
5. Extract protagonist skill changes if any
6. Extract character-related facts

JSON:"""


def get_tool_schema() -> dict:
    """Return JSON schema for CharactersExtraction."""
    return CharactersExtraction.model_json_schema()
