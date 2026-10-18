"""The PC name chosen in the wizard is authoritative over the world builder's (#28).

Works on the parsed world JSON before WorldGeneration validation. The input is never
modified (a changed world is a new dict; an unchanged one is returned as is), and the only
I/O is a WARNING log when the default name steps in.

When the model named the PC differently, its mentions follow the rename:
- a string that is exactly the model's name (a reference) becomes the wizard's name;
- in free text, whole-name mentions of the model's name become the wizard's name and, for
  a multi-word model name, whole-word mentions of its first name become the wizard's first
  name. Matching is case-insensitive, with Unicode word boundaries that also treat '-' as
  part of a name ("Ana" never hits "Anaïs", "banane" or "Ana-Lou"); the straight (') and
  typographic (’) apostrophes are the same character ("N'Diaye" matches "N’Diaye");
- the wizard's name is matched in the same single pass and kept as is, so the rename
  never rewrites inside it ("Kira" -> "Kira Voss" leaves "Kira Voss" alone) and running
  it twice changes nothing;
- a free-text form that also appears as a word in another entity's name is not
  rewritten (only exact references are).

The regex is built from the original strings, never from their casefold alone: casefold()
rewrites "ß" to "ss", "İ" to "i̇" and "ς" to "σ", which `re.IGNORECASE` (simple case
folding) would never match again, so "Kira Weiß" would not be recognised as the target.
When the casefold spells a name differently it is added as a second spelling of the same
name, so "WEISS" and "Weiss" are "Weiß" too. Whole names are compared with casefold().

Known limits, on purpose:
- hyphenated compounds are distinct names: '-' counts as part of a name, so renaming
  "Élodie" leaves "Élodie-Rose" (another person, or a place) untouched, and "Jean" never
  rewrites "Jean-Pierre";
- surname-only mentions of a multi-word model name are left alone ("Kira Voss" -> "Ana Lo"
  keeps "Voss rit."), because a bare surname may name another member of the family.

With a blank wizard name the model's name is kept, unless it is unusable (blank, a copied
"<prénom inventé>" marker or any '<'/'>', or PROTAGONIST_REF): world generation must not
fail after the paid call because of it, so DEFAULT_PROTAGONIST_NAME replaces it, with the
same rename pass, and a WARNING without story text is logged.
"""

import logging
import re
from collections.abc import Callable
from typing import cast

from schema import DEFAULT_PROTAGONIST_NAME, is_protagonist_ref, is_usable_protagonist_name

logger = logging.getLogger(__name__)

_ENTITY_LISTS = ("characters", "locations", "organizations", "inventory")
_EITHER_APOSTROPHE = "['’]"
_APOSTROPHE = re.compile(_EITHER_APOSTROPHE)


def chosen_name(character: dict | None) -> str | None:
    """PC name typed in the wizard; None when blank or unusable (the API refuses the latter)."""
    name = (character or {}).get("name")
    return name.strip() if is_usable_protagonist_name(name) else None


def apply_chosen_name(parsed: dict | None, character: dict | None) -> dict | None:
    """Store the wizard's PC name whatever the model returned; keep the model's when blank,
    unless it is unusable (then DEFAULT_PROTAGONIST_NAME)."""
    # The parser may hand back a JSON array or scalar: world validation refuses it cleanly.
    if not isinstance(parsed, dict):
        return parsed
    protagonist = parsed.get("protagonist")
    if not isinstance(protagonist, dict):
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
    if old and old.casefold() != name.casefold():
        # _walk keeps the container types: a dict comes back as a dict.
        renamed = cast(dict, _walk(parsed, _renamer(old, name, _other_entity_names(parsed))))
    else:
        renamed = {**parsed, "protagonist": dict(protagonist)}
    renamed["protagonist"]["name"] = name
    return renamed


def _whole(text: str) -> str:
    """Whole-name pattern: not preceded or followed by a word character or '-'; either
    apostrophe matches the other."""
    escaped = _APOSTROPHE.sub(_EITHER_APOSTROPHE, re.escape(text))
    return rf"(?<![\w-]){escaped}(?![\w-])"


def _same_name(text: str, name: str) -> bool:
    """`text` is `name` written differently: other case ("WEISS"/"Weiß") or apostrophe."""
    return text.casefold() == name.casefold() or bool(re.fullmatch(_whole(name), text, re.IGNORECASE))


def _renamer(old: str, new: str, other_names: list[str]) -> Callable[[str], str]:
    """Rewrite one string: exact reference, else whole-name mentions in one regex pass."""
    targets = {old: new}
    old_first, new_first = old.split()[0], new.split()[0]
    if old_first.casefold() != old.casefold() and is_usable_protagonist_name(old):
        targets[old_first] = new_first
    free = [form for form in targets
            if not any(re.search(_whole(form), n, re.IGNORECASE) for n in other_names)]
    references = [old, *(form for form in free if form != old)]
    # Longest first, the wizard's name included (kept as is, so a mention is matched once, as a
    # whole). Named groups tell which original name matched, whatever its spelling in the text.
    spellings = sorted(((form, s) for form in [*targets, new] for s in _spellings(form)),
                       key=lambda fs: len(fs[1]), reverse=True)
    pattern = re.compile("|".join(f"(?P<a{i}>{_whole(s)})" for i, (_, s) in enumerate(spellings)),
                         re.IGNORECASE)
    by_group = {f"a{i}": form for i, (form, _) in enumerate(spellings)}

    def replacement(m: re.Match) -> str:
        form = by_group[str(m.lastgroup)]
        return targets[form] if form in free else m.group(0)

    def rewrite(value: str) -> str:
        if any(_same_name(value.strip(), ref) for ref in references):
            return new  # the whole string is a reference to the PC
        return pattern.sub(replacement, value) if free else value

    return rewrite


def _spellings(name: str) -> list[str]:
    """The name, plus its casefold when `re.IGNORECASE` would not match it ("Weiß" -> "weiss")."""
    folded = name.casefold()
    return [name] if re.fullmatch(_whole(name), folded, re.IGNORECASE) else [name, folded]


def _other_entity_names(parsed: dict) -> list[str]:
    names = [item.get("name") for key in _ENTITY_LISTS for item in parsed.get(key) or []
             if isinstance(item, dict)]
    companion = parsed.get("companion")
    if isinstance(companion, dict):
        names.append(companion.get("name"))
    return [n for n in names if isinstance(n, str)]


def _walk(value: object, rewrite: Callable[[str], str]) -> object:
    if isinstance(value, dict):
        return {k: _walk(v, rewrite) for k, v in value.items()}
    if isinstance(value, list):
        return [_walk(v, rewrite) for v in value]
    if isinstance(value, str):
        return rewrite(value)
    return value
