"""Deterministic alias derivation at creation or renaming (spec §4.3); no LLM.

A proper name gives its label, the label without its titles and its first and last words.
A descriptor gives its label: ldvelh_norm drops one leading determiner, so its forms with
and without the determiner share one norm and one alias matches both. Aliases sharing a
norm are kept once (first wins), since the registry is unique on (entity, alias_norm).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from services.identity.lexicon import Lexicon
from services.identity.normalize import Normalizer

_EDGE_PUNCTUATION = re.compile(r"^[\W_]+|[\W_]+$")


@dataclass(frozen=True)
class AliasSpec:
    text: str
    kind: str
    known: bool
    secret: bool = False


def derive(
    label: str,
    *,
    kind: Literal["true_name", "descriptor"],
    known: bool,
    secret: bool = False,
    normalizer: Normalizer,
    lexicon: Lexicon,
) -> list[AliasSpec]:
    """Aliases of `label`. A true name's aliases share its `known`; a descriptor is what the
    protagonist sees, so its aliases are always known."""
    label = " ".join(label.split())
    if kind == "descriptor":
        forms = [(label, "descriptor")]
        known = True
    else:
        untitled = normalizer.strip_title(label, lexicon)
        forms = [(label, "label"), (untitled, "title")]
        forms += [
            (word, "short") for word in _short_words(untitled, normalizer, lexicon)
        ]
    aliases, seen = [], set()
    for text, alias_kind in forms:
        norm = normalizer.norm(text)
        if text and norm and norm not in seen:
            seen.add(norm)
            aliases.append(AliasSpec(text, alias_kind, known, secret))
    return aliases


def _short_words(untitled: str, normalizer: Normalizer, lexicon: Lexicon) -> list[str]:
    """Last then first word of a multi-word name, when distinctive enough."""
    words = [_EDGE_PUNCTUATION.sub("", w) for w in untitled.split()]
    if len(words) <= 1:
        return []
    picked = []
    for word in (words[-1], words[0]):
        key = normalizer.key(word)
        if (
            len(key) >= normalizer.config.token_min_len
            and key not in lexicon.titles
            and key not in lexicon.stop_words
        ):
            picked.append(word)
    return picked
