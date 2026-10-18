"""The PC name chosen in the wizard is authoritative over the world builder's (#28).

Pure: works on the parsed world JSON before WorldGeneration validation.

When the model named the PC differently, its mentions follow the rename:
- a string that is exactly the model's name (a reference) becomes the wizard's name;
- in free text, whole-name mentions of the model's name become the wizard's name and, for
  a multi-word model name, whole-word mentions of its first name become the wizard's first
  name. Matching is case-insensitive, with Unicode word boundaries that also treat '-' as
  part of a name ("Ana" never hits "Anaïs", "banane" or "Ana-Lou");
- the wizard's name is matched in the same single pass and kept as is, so the rename
  never rewrites inside it ("Kira" -> "Kira Voss" leaves "Kira Voss" alone) and running
  it twice changes nothing;
- a free-text form that also appears as a word in another entity's name is not
  rewritten (only exact references are).

Hyphenated compounds are distinct names on purpose: '-' counts as part of a name, so
renaming "Élodie" leaves "Élodie-Rose" (another person, or a place) untouched, and "Jean"
never rewrites "Jean-Pierre".

With a blank wizard name the model's name is kept, unless it is unusable (blank, a copied
"<prénom inventé>" marker or any '<'/'>', or PROTAGONIST_REF): world generation must not
fail after the paid call because of it, so DEFAULT_PROTAGONIST_NAME replaces it, with the
same rename pass, and a WARNING without story text is logged.
"""

import logging
import re
from collections.abc import Callable

from schema.core import DEFAULT_PROTAGONIST_NAME, is_protagonist_ref, is_usable_protagonist_name

logger = logging.getLogger(__name__)

_ENTITY_LISTS = ("characters", "locations", "organizations", "inventory")


def chosen_name(character: dict | None) -> str | None:
    """PC name typed in the wizard; None when blank or unusable (the API refuses the latter)."""
    name = (character or {}).get("name")
    return name.strip() if is_usable_protagonist_name(name) else None


def apply_chosen_name(parsed: dict | None, character: dict | None) -> dict | None:
    """Store the wizard's PC name whatever the model returned; keep the model's when blank,
    unless it is unusable (then DEFAULT_PROTAGONIST_NAME)."""
    protagonist = (parsed or {}).get("protagonist")
    if parsed is None or not isinstance(protagonist, dict):
        return parsed
    previous = protagonist.get("name")
    name = chosen_name(character)
    if name is None:
        if is_usable_protagonist_name(previous):
            return parsed
        logger.warning("[INIT] Unusable protagonist name from the world builder:"
                       f" stored as '{DEFAULT_PROTAGONIST_NAME}'")
        name = DEFAULT_PROTAGONIST_NAME
    # PROTAGONIST_REF references already resolve to the PC: never rename them.
    old = previous.strip() if isinstance(previous, str) and not is_protagonist_ref(previous) else ""
    renamed = parsed
    if old and old.casefold() != name.casefold():
        renamed = _walk(parsed, _renamer(old, name, _other_entity_names(parsed)))
    renamed["protagonist"]["name"] = name
    return renamed


def _whole(text: str) -> str:
    """Whole-name pattern: not preceded or followed by a word character or '-'."""
    return rf"(?<![\w-]){re.escape(text)}(?![\w-])"


def _renamer(old: str, new: str, other_names: list[str]) -> Callable[[str], str]:
    """Rewrite one string: exact reference, else whole-name mentions in one regex pass."""
    forms = {old.casefold(): new}
    old_first, new_first = old.split()[0], new.split()[0]
    if old_first.casefold() != old.casefold() and is_usable_protagonist_name(old):
        forms.setdefault(old_first.casefold(), new_first)
    free = {form: target for form, target in forms.items()
            if not any(re.search(_whole(form), n, re.IGNORECASE) for n in other_names)}
    # Longest first, the wizard's name included: a mention is matched once, as a whole.
    alternatives = sorted({new.casefold(), *free}, key=len, reverse=True)
    pattern = re.compile("|".join(_whole(a) for a in alternatives), re.IGNORECASE)

    def rewrite(value: str) -> str:
        key = value.strip().casefold()
        if key == old.casefold() or (key in free and key != new.casefold()):
            return new  # the whole string is a reference to the PC
        if not free:
            return value
        return pattern.sub(lambda m: free.get(m.group(0).casefold(), m.group(0)), value)

    return rewrite


def _other_entity_names(parsed: dict) -> list[str]:
    names = [item.get("name") for key in _ENTITY_LISTS for item in parsed.get(key) or []
             if isinstance(item, dict)]
    companion = parsed.get("companion")
    if isinstance(companion, dict):
        names.append(companion.get("name"))
    return [n for n in names if isinstance(n, str)]


def _walk(value, rewrite: Callable[[str], str]):
    if isinstance(value, dict):
        return {k: _walk(v, rewrite) for k, v in value.items()}
    if isinstance(value, list):
        return [_walk(v, rewrite) for v in value]
    if isinstance(value, str):
        return rewrite(value)
    return value
