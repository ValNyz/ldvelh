"""
LDVELH - Shared Extraction Rules
Common instructions for all specialized extractors.
"""

STRICT_KEYS_RULE = """## STRICT KEY CONSTRAINT

You MUST use EXACTLY the JSON keys listed in the output format.
- Do NOT add extra keys
- Do NOT invent variants (e.g. "type" instead of "fact_type")
- Do NOT nest data in unplanned sub-objects
- If some information has no matching key, ignore it"""

ENTITY_MATCHING_RULE = """## ENTITY NAME MATCHING

- Use EXACT names from the known entities list when referencing existing entities
- Case-insensitive matching, but prefer the canonical casing from the list
- For new entities, use the name as it appears in the narrative text"""

FACT_RULES = """## FACTS

- semantic_key: lowercase ASCII format subject:verb:object (e.g. "marie:reveals:sick_mother")
- importance: 5=game-changer, 4=significant, 3=notable, 2=minor, 1=ambient
- participants[]: entity_ref (string), role (actor|witness|target|mentioned)
- fact_type values: revelation, statement, promise, request, refusal, action, npc_action,
  observation, state_change, encounter, interaction, conflict, acquisition, loss,
  decision, realization"""

CORE_RULES = """## CORE RULES

1. Extract ONLY what is EXPLICIT in the narrative text
2. Do NOT invent or deduce — only extract what is clearly stated
3. Credits are handled by the narrator — do NOT extract them
4. Inventory hints are already applied — only create detailed object records for new acquisitions
5. Deduplicate: an entity/fact should appear only once
6. known_by_protagonist=true if Valentin SAW/HEARD the name"""

RESOLUTION_SECTION_HEADER = """## ENTITY RESOLUTION MAP

The following narrative mentions have been pre-resolved to canonical entity names.
When extracting data about these entities, you MUST use the CANONICAL name (right side),
NOT the narrative mention (left side). This tells you WHO is being referred to in the text.

For EXISTING entities: use the exact canonical name from the database.
For NEW entities: use the suggested canonical name.

"""
