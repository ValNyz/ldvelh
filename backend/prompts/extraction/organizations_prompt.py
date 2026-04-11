"""
LDVELH - Organizations Extractor Prompt
Handles organization CRUD, ambient updates, and organization-related facts.
"""

from schema.extraction import OrganizationsExtraction

from .shared import CORE_RULES, ENTITY_MATCHING_RULE, FACT_RULES, STRICT_KEYS_RULE

SYSTEM_PROMPT = f"""Tu es l'extracteur d'ORGANISATIONS d'un jeu de rôle narratif sur une station spatiale.
Tu analyses les textes narratifs et extrais les changements relatifs aux organisations.

## FORMAT DE SORTIE

```json
{{
    "entities_created": [
        {{
            "entity_type": "organization",
            "name": "Consortium Hélios",
            "known_by_protagonist": true,
            "data": {{
                "org_type": "corporation",
                "domain": "énergie",
                "size": "large",
                "description": "Conglomérat énergétique aux pratiques douteuses",
                "reputation": "puissant mais controversé",
                "headquarters_ref": "Tour Hélios",
                "founding_cycle": -3000
            }}
        }}
    ],
    "entities_updated": [
        {{
            "entity_ref": "Symbiose Tech",
            "entity_type": "organization",
            "changes": {{
                "reputation": "en crise après le scandale"
            }}
        }}
    ],
    "ambient_updates": [
        {{
            "entity_ref": "Symbiose Tech",
            "entity_type": "organization",
            "ambient": "Tension palpable dans les bureaux, réunions à huis clos"
        }}
    ],
    "facts": [
        {{
            "fact_type": "revelation",
            "description": "Symbiose Tech est en négociation secrète avec un investisseur",
            "semantic_key": "symbiose_tech:negocie:investisseur_secret",
            "importance": 4,
            "participants": [
                {{"entity_ref": "Symbiose Tech", "role": "actor"}}
            ]
        }}
    ]
}}
```

## ORGANIZATION DATA FIELDS

data (for entities_created):
- org_type (string), domain (string), size (small|medium|large|station-wide)
- description (string), reputation (string)
- headquarters_ref (string — location name), founding_cycle (int)

changes (for entities_updated): same keys as data above.

## AMBIENT UPDATES

For each organization affected by an active arc, generate an ambient text (max 200 chars)
describing the VISIBLE effect: atmosphere in offices, employee behavior, public perception.

{STRICT_KEYS_RULE}

{ENTITY_MATCHING_RULE}

{FACT_RULES}

{CORE_RULES}

## ORGANIZATION-SPECIFIC RULES

1. Only create entities with entity_type="organization"
2. org_type values: company, guild, government, ngo, informal, criminal
3. Extract only ORGANIZATION-related facts (business events, reputation changes)
4. For size, use: small (<10), medium (10-100), large (100+), station-wide"""


def build_user_prompt(
    narrative_text: str,
    cycle: int,
    known_organizations: list[dict],
    active_arcs_with_orgs: list[dict] | None = None,
) -> str:
    """Build the user prompt for the organizations extractor."""
    texts_joined = narrative_text

    org_lines = []
    for org in known_organizations[:20]:
        name = org.get("name", "?")
        org_type = org.get("org_type", "")
        domain = org.get("domain", "")
        ambient = org.get("ambient", "")
        line = f"- {name}"
        if org_type:
            line += f" ({org_type})"
        if domain:
            line += f" — {domain}"
        if ambient:
            line += f" — ambient: {ambient}"
        org_lines.append(line)
    orgs_str = "\n".join(org_lines) if org_lines else "None"

    arcs_section = ""
    if active_arcs_with_orgs:
        arcs_lines = []
        for arc in active_arcs_with_orgs:
            parts = ", ".join(arc.get("participants", [])) or "none"
            arcs_lines.append(
                f"- {arc['title']} [{arc.get('domain', '?')}] "
                f"(intensity {arc.get('intensity', '?')}/5): {parts}"
            )
        arcs_section = "\n\nActive arcs involving organizations (for ambient_updates):\n" + "\n".join(arcs_lines)

    return f"""## CONTEXT
- Cycle: {cycle}
- Known organizations:
{orgs_str}
{arcs_section}

## NARRATIVE TEXTS

{texts_joined}

## INSTRUCTIONS
1. Extract NEW organizations not in the known list
2. Extract updates to existing organizations (reputation, domain, etc.)
3. Generate ambient_updates for organizations affected by active arcs
4. Extract organization-related facts

JSON:"""


def get_tool_schema() -> dict:
    """Return JSON schema for OrganizationsExtraction."""
    return OrganizationsExtraction.model_json_schema()
