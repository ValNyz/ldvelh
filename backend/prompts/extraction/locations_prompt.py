"""
LDVELH - Locations Extractor Prompt
Handles location CRUD, stub enrichment, ambient updates, and location-related facts.
"""

from schema.extraction import LocationsExtraction

from .shared import CORE_RULES, ENTITY_MATCHING_RULE, FACT_RULES, STRICT_KEYS_RULE

SYSTEM_PROMPT = f"""Tu es l'extracteur de LIEUX d'un jeu de rôle narratif sur une station spatiale.
Tu analyses les textes narratifs et extrais les changements relatifs aux lieux.

## FORMAT DE SORTIE

```json
{{
    "entities_created": [
        {{
            "entity_type": "location",
            "name": "Atelier Mécanique B",
            "known_by_protagonist": true,
            "data": {{
                "location_type": "workshop",
                "sector": "Quartier Ouvrier",
                "description": "Petit atelier encombré, outils rouillés sur les murs",
                "atmosphere": "graisseux et bruyant",
                "accessible": true,
                "notable_features": ["établi central", "odeur d'huile"],
                "typical_crowd": "mécaniciens",
                "operating_hours": "08h-20h",
                "price_range": null,
                "parent_location_ref": null
            }}
        }}
    ],
    "entities_updated": [
        {{
            "entity_ref": "Le Quart de Cycle",
            "entity_type": "location",
            "changes": {{
                "atmosphere": "tendu après l'incident",
                "accessible": false
            }}
        }}
    ],
    "ambient_updates": [
        {{
            "entity_ref": "Serres Hydro-7",
            "entity_type": "location",
            "ambient": "L'éclairage vacille depuis la panne, ambiance inquiétante"
        }}
    ],
    "facts": [
        {{
            "fact_type": "observation",
            "description": "Le Terminal Quai 7 est en travaux, accès limité",
            "semantic_key": "terminal_quai_7:en_travaux:acces_limite",
            "importance": 3,
            "participants": [
                {{"entity_ref": "Terminal Quai 7", "role": "target"}}
            ]
        }}
    ]
}}
```

## LOCATION DATA FIELDS

data (for entities_created):
- location_type (string), sector (string), description (string)
- atmosphere (string), accessible (bool)
- notable_features (list of strings), typical_crowd (string)
- operating_hours (string), price_range (string)
- parent_location_ref (string — name of parent location)

changes (for entities_updated): same keys as data above.

## STUB ENRICHMENT

Stub locations are locations with no description. When narrative text reveals details
about a stub location, use entities_updated with changes to fill in the missing fields:
description, location_type, sector, atmosphere.

## AMBIENT UPDATES

For each location affected by an active arc or event, generate an ambient text (max 200 chars)
describing the VISIBLE effect: atmosphere shift, physical changes, crowd behavior.

{STRICT_KEYS_RULE}

{ENTITY_MATCHING_RULE}

{FACT_RULES}

{CORE_RULES}

## LOCATION-SPECIFIC RULES

1. Only create entities with entity_type="location"
2. For locations the protagonist hasn't visited yet: known_by_protagonist=false
3. Prioritize enriching stub locations (entities_updated with full data)
4. Extract only LOCATION-related facts (observations about places)"""


def build_user_prompt(
    narrative_text: str,
    cycle: int,
    known_locations: list[dict],
    stub_locations: list[str] | None = None,
    active_arcs_with_locations: list[dict] | None = None,
) -> str:
    """Build the user prompt for the locations extractor."""
    texts_joined = narrative_text

    loc_lines = []
    for loc in known_locations[:40]:
        name = loc.get("name", "?")
        sector = loc.get("sector", "")
        loc_type = loc.get("location_type", "")
        ambient = loc.get("ambient", "")
        line = f"- {name}"
        if sector:
            line += f" [{sector}]"
        if loc_type:
            line += f" ({loc_type})"
        if ambient:
            line += f" — ambient: {ambient}"
        loc_lines.append(line)
    locs_str = "\n".join(loc_lines) if loc_lines else "None"

    stubs_section = ""
    if stub_locations:
        stubs_str = ", ".join(stub_locations)
        stubs_section = (
            f"\n\nStub locations (no description — enrich via entities_updated):\n"
            f"- {stubs_str}\n"
            f"For each stub: entity_ref = exact name, changes = "
            f"{{description, location_type, sector, atmosphere}}"
        )

    arcs_section = ""
    if active_arcs_with_locations:
        arcs_lines = []
        for arc in active_arcs_with_locations:
            parts = ", ".join(arc.get("participants", [])) or "none"
            arcs_lines.append(
                f"- {arc['title']} [{arc.get('domain', '?')}] "
                f"(intensity {arc.get('intensity', '?')}/5): {parts}"
            )
        arcs_section = "\n\nActive arcs involving locations (for ambient_updates):\n" + "\n".join(arcs_lines)

    return f"""## CONTEXT
- Cycle: {cycle}
- Known locations:
{locs_str}
{stubs_section}
{arcs_section}

## NARRATIVE TEXTS

{texts_joined}

## INSTRUCTIONS
1. Extract NEW locations not in the known list
2. Enrich STUB locations with full details if the narrative describes them
3. Extract updates to existing locations (atmosphere, accessibility, etc.)
4. Generate ambient_updates for locations affected by active arcs
5. Extract location-related facts

JSON:"""


def get_tool_schema() -> dict:
    """Return JSON schema for LocationsExtraction."""
    return LocationsExtraction.model_json_schema()
