"""Deterministic alias derivation at creation or renaming (spec §4.3); no LLM.

A name gives its full form (kind `true_name` for a character's true name, so that its
`known` flag says whether the protagonist knows it, `label` otherwise), the form without
its titles and its first and last words (elided words split off: « d'Ombelle » → « Ombelle »).
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
    kind: Literal["true_name", "label", "descriptor"],
    known: bool,
    secret: bool = False,
    normalizer: Normalizer,
    lexicon: Lexicon,
) -> list[AliasSpec]:
    """Aliases of `label`. A name's aliases share its `known`; a descriptor is what the
    protagonist sees, so its aliases are always known."""
    label = " ".join(label.split())
    if kind == "descriptor":
        forms = [(label, "descriptor")]
        known = True
    else:
        untitled = normalizer.strip_title(label, lexicon)
        forms = [(label, kind), (untitled, "title")]
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
    words = [
        normalizer.drop_elided(_EDGE_PUNCTUATION.sub("", w), lexicon.elided)
        for w in untitled.split()
    ]
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
