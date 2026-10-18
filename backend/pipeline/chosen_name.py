"""The PC name chosen in the wizard is authoritative over the world builder's (#28).

Pure: works on the parsed world JSON before WorldGeneration validation.
"""

import re

_ENTITY_LISTS = ("characters", "locations", "organizations", "inventory")


def chosen_name(character: dict | None) -> str | None:
    """PC name typed in the wizard; None when left blank (the world builder invents one)."""
    name = (character or {}).get("name")
    return (name.strip() or None) if isinstance(name, str) else None


def apply_chosen_name(parsed: dict | None, character: dict | None) -> dict | None:
    """Store the wizard's PC name whatever the model returned; keep the model's when blank.

    When the model used another name, the references to it follow: every string equal to
    it (refs, involved entities) becomes the chosen name, and so does every whole-word
    mention in free text, unless another entity's name contains it (then only exact refs).
    """
    name = chosen_name(character)
    protagonist = (parsed or {}).get("protagonist")
    if parsed is None or not name or not isinstance(protagonist, dict):
        return parsed
    previous = protagonist.get("name")
    protagonist["name"] = name
    if isinstance(previous, str) and previous.strip() and previous.strip().lower() != name.lower():
        old = previous.strip()
        word = re.compile(rf"(?<!\w){re.escape(old)}(?!\w)")
        in_free_text = not any(word.search(n) for n in _other_entity_names(parsed))
        return _rename(parsed, old, name, word if in_free_text else None)
    return parsed


def _other_entity_names(parsed: dict) -> list[str]:
    names = [item.get("name") for key in _ENTITY_LISTS for item in parsed.get(key) or []
             if isinstance(item, dict)]
    companion = parsed.get("companion")
    if isinstance(companion, dict):
        names.append(companion.get("name"))
    return [n for n in names if isinstance(n, str)]


def _rename(value, old: str, new: str, word: re.Pattern | None):
    if isinstance(value, dict):
        return {k: _rename(v, old, new, word) for k, v in value.items()}
    if isinstance(value, list):
        return [_rename(v, old, new, word) for v in value]
    if isinstance(value, str):
        if value.strip().lower() == old.lower():
            return new
        return word.sub(new, value) if word else value
    return value
