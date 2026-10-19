"""
LDVELH - Inventory Extractor Prompt
Handles object creation deduplicated by object label, inventory changes, and inventory-related facts.
"""

from schema import PROTAGONIST_REF
from schema.extraction import InventoryExtraction

from .shared import CORE_RULES, ENTITY_MATCHING_RULE, FACT_RULES, STRICT_KEYS_RULE

SYSTEM_PROMPT = f"""Tu es l'extracteur d'INVENTAIRE d'un jeu de rôle narratif sur une station spatiale.
Tu analyses les textes narratifs et crées les fiches d'objets acquis et les changements d'inventaire.

## FORMAT DE SORTIE

```json
{{
    "objects_created": [
        {{
            "name": "Carte d'accès niveau 2",
            "category": "tech",
            "description": "Carte magnétique bleue avec puce intégrée",
            "transportable": true,
            "stackable": false,
            "base_value": 50,
            "quantity": 1,
            "from_hint": "Carte d'accès temporaire"
        }}
    ],
    "inventory_changes": [
        {{
            "action": "acquire",
            "object_ref": null,
            "object_hint": "Carte d'accès temporaire",
            "quantity_delta": 1,
            "reason": "Donnée par l'accueil"
        }},
        {{
            "action": "use",
            "object_ref": "Terminal personnel",
            "quantity_delta": 1,
            "reason": "Consulté pour chercher l'itinéraire"
        }}
    ],
    "facts": [
        {{
            "fact_type": "acquisition",
            "description": "Kira reçoit une carte d'accès niveau 2 de l'accueil",
            "semantic_key": "kira:receives:carte_acces_2",
            "importance": 3,
            "participants": [
                {{"entity_ref": "{PROTAGONIST_REF}", "role": "actor"}}
            ]
        }}
    ]
}}
```

## OBJECT DEDUP

Existing objects are listed by their label.
- If the item is an existing object (same object, even written with another case, accents
  or article), do NOT create a new objects_created entry.
  Instead, use inventory_changes with object_ref = the existing object label, exactly as listed.
- This prevents the same object being recorded twice under two spellings.

## OBJECT FIELDS

- name (string max 100): display name (the object label)
- category: tech, weapon, clothing, food, document, tool, misc
- description (string max 300): brief description
- transportable (bool): can the protagonist carry it?
- stackable (bool): can multiple units stack?
- base_value (int|null): credit value
- quantity (int): how many acquired
- from_hint (string max 200): the original inventory_hint item_name that triggered this

## INVENTORY CHANGES

- action: acquire, lose, use
- For "acquire" with a new object: set object_ref=null, object_hint=item description
- For "acquire" with an existing object: set object_ref=existing object label
- For "lose" and "use": object_ref is required (exact name of existing object)

{STRICT_KEYS_RULE}

{ENTITY_MATCHING_RULE}

{FACT_RULES}

{CORE_RULES}

## INVENTORY-SPECIFIC RULES

1. Only create objects_created for items that need a DETAILED record
2. Match inventory_hints from the narrator (from_hint field) to formalize them
3. Check existing object labels before creating — if a match exists, use inventory_changes instead
4. Extract only INVENTORY-related facts (acquisitions, losses, notable uses)"""


def build_user_prompt(
    narrative_text: str,
    cycle: int,
    existing_labels: list[str],
    inventory_hints: list[dict] | None = None,
    known_objects: list[dict] | None = None,
    engine_object_addon: str | None = None,
) -> str:
    """Build the user prompt for the inventory extractor."""
    texts_joined = narrative_text

    labels_str = ", ".join(existing_labels[:50]) if existing_labels else "None"

    hints_section = ""
    if inventory_hints:
        items = [
            f"- {h.get('item_name', '?')} ({h.get('action', '?')}) — {h.get('item_description', '')}"
            for h in inventory_hints
        ]
        hints_section = "\n\nInventory hints from narrator (to formalize):\n" + "\n".join(items)

    objects_section = ""
    if known_objects:
        obj_lines = [f"- {o.get('name', '?')} [{o.get('category', '?')}]" for o in known_objects[:30]]
        objects_section = "\n\nKnown objects in inventory:\n" + "\n".join(obj_lines)

    engine_section = ""
    if engine_object_addon:
        engine_section = f"\n\n## ENGINE-SPECIFIC OBJECT DATA\n{engine_object_addon}"

    return f"""## CONTEXT
- Cycle: {cycle}
- Existing object labels (do NOT create duplicates): {labels_str}
{objects_section}
{hints_section}
{engine_section}

## NARRATIVE TEXTS

{texts_joined}

## INSTRUCTIONS
1. For each inventory_hint, create objects_created if the item is new (check the object labels)
2. If the object already exists, use inventory_changes with object_ref instead
3. Extract inventory_changes for items lost or used
4. Extract inventory-related facts

JSON:"""


def get_tool_schema() -> dict:
    """Return JSON schema for InventoryExtraction."""
    return InventoryExtraction.model_json_schema()
