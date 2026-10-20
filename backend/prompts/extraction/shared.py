"""
LDVELH - Shared Extraction Rules
Common instructions for all specialized extractors.
"""

from typing import Protocol

from packs.loader import Example
from schema import PROTAGONIST_REF

SEPARATOR = " · "

STRICT_KEYS_RULE = """## STRICT KEY CONSTRAINT

You MUST use EXACTLY the JSON keys listed in the output format.
- Do NOT add extra keys
- Do NOT invent variants (e.g. "type" instead of "fact_type")
- Do NOT nest data in unplanned sub-objects
- If some information has no matching key, ignore it"""

ENTITY_REFERENCE_RULE = f"""## ENTITY REFERENCES

- Reference every entity by its handle (E<n>) from the ENTITIES IN THIS SCENE section,
  in every reference field (entity_ref, source_ref, target_ref, owner_ref, location_ref,
  object_ref, involved_entities, participants)
- An entity the narrative introduces that is absent from that list goes in
  proposed_entities, with its label as the text gives it: never create an entity
  anywhere else, and never propose one the list already holds
- The player character is ALWAYS referenced as "{PROTAGONIST_REF}" in reference fields,
  never by name or handle. In free text (description, summary) use the name given in
  the PROTAGONIST section"""

SCENE_ENTITIES_HEADER = "## ENTITIES IN THIS SCENE"


class SceneLine(Protocol):
    """An entity of the scene (domain.identity.SceneEntity)."""

    handle: str
    entity_type: str
    label: str
    known: bool
    is_new: bool


class ExtractionLexicon(Protocol):
    """What the extraction prompts read of a game's lexicon (Lexicon)."""

    extraction_examples: list[Example]
    entity_type_vocab: dict[str, list[str]]


def _scene_line(entity: SceneLine) -> str:
    return SEPARATOR.join(
        (
            entity.handle,
            entity.entity_type,
            entity.label,
            "known" if entity.known else "unknown",
            "new" if entity.is_new else "existing",
        )
    )


def scene_entities_section(
    entities: list[SceneLine], lexicon: ExtractionLexicon
) -> str:
    """User-prompt section listing the entities of the scene by handle, with the
    examples of the game's packs (genre, else language) and the genre's words for each
    entity type: no example of a universe written here."""
    lines = [f"- {_scene_line(e)}" for e in entities] or ["- (none)"]
    parts = [
        f"\n\n{SCENE_ENTITIES_HEADER}\n"
        "Reference every entity by its handle; propose an entity absent from this list"
        " in proposed_entities, never create it.\n" + "\n".join(lines)
    ]
    vocab = [
        f"- {entity_type}: {', '.join(words)}"
        for entity_type, words in lexicon.entity_type_vocab.items()
        if words
    ]
    if vocab:
        parts.append("Words of this world for each entity type:\n" + "\n".join(vocab))
    if lexicon.extraction_examples:
        parts.append(
            "Examples:\n"
            + "\n".join(
                f"- {e.input}\n  -> {e.output}" for e in lexicon.extraction_examples
            )
        )
    return "\n\n".join(parts)


def protagonist_section(name: str | None) -> str:
    """User-prompt section naming the player character, empty before world generation."""
    if not name:
        return ""
    return (
        f'\n\n## PROTAGONIST\nThe player character is {name}: write "{PROTAGONIST_REF}"'
        f' in reference fields, "{name}" in free text.'
    )


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
