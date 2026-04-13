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

FACT_RULES = """## FACTS (Entity Knowledge Only)

Facts are PERMANENT TRUTHS about entities — not narrative events (those go in chronology).
Only extract facts that will still be true next cycle.

- semantic_key: lowercase ASCII format subject:verb:object (e.g. "ossek:deals_in:codes")
- importance: minimum 3 (no ambient noise). 5=game-changer, 4=significant, 3=notable
- participants[]: REQUIRED — each fact MUST have at least one participant (the entity it's about)
- fact_type values: revelation, trait, secret, ability
  - revelation: something discovered about an entity
  - trait: permanent characteristic
  - secret: hidden knowledge
  - ability: what an entity can do
- Do NOT extract: observations, actions, state changes, encounters, atmosphere — those are transient"""

CORE_RULES = """## CORE RULES

1. Extract ONLY what is EXPLICIT in the narrative text
2. Do NOT invent or deduce — only extract what is clearly stated
3. Credits are handled by the narrator — do NOT extract them
4. Inventory hints are already applied — only create detailed object records for new acquisitions
5. Deduplicate: an entity/fact should appear only once
6. known_by_protagonist=true if the protagonist SAW/HEARD the name"""

RESOLUTION_SECTION_HEADER = """## ENTITY RESOLUTION MAP (MANDATORY)

The following entities have been identified in this scene by the resolver.
You MUST include ALL of them in your extraction output — do NOT skip any.
Use the CANONICAL name (right side), NOT the narrative mention (left side).

For EXISTING entities: update their data if the narrative adds new information.
For NEW entities: create them with the suggested canonical name.

"""
