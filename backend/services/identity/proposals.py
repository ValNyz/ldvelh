"""The close-name step of an extractor's proposal (spec §4.6, C6-C8): which live entity a
proposed name designates although no label or alias holds it exactly. No model call.

A wrongful fold is worse than a duplicate (spec §4.5.4): the comparison is strict.
- Only whole names compare: an entity's label, true name or descriptor, never a derived
  short form (« Kessler » would fold « Jon Kessler » into « Mira Kessler »).
- Names compare by their content words (`Normalizer.tokens`: articles, stop words and
  titles of the packs left out), so « Halle Cordiers » is « la Halle aux Cordiers ».
- Two names whose content words differ by a number or by a distinctive word (at least
  the pack's `min_distinctive_token_len` letters) are two entities: « Carte niveau 3 » is
  not « Carte niveau 2 », « Clé rouillée » is not « Clé ».
- The similarity must hold both ways (the lower of the two run similarities), from
  `IdentityConfig.create_from_extractor`; two entities equally close give no pick.
"""

from __future__ import annotations

from uuid import UUID

from services.identity.lexicon import Lexicon
from services.identity.normalize import Normalizer
from utils.trigrams import word_run_similarity


def content_words(text: str, normalizer: Normalizer, lexicon: Lexicon) -> list[str]:
    """The normalised content words of a name, numbers included."""
    return normalizer.tokens(text, lexicon, min_len=1)


def _distinct(a: list[str], b: list[str], lexicon: Lexicon) -> bool:
    """The two word sets differ by a number or by a distinctive word."""
    return any(
        any(ch.isdigit() for ch in word)
        or len(word) >= lexicon.min_distinctive_token_len
        for word in set(a) ^ set(b)
    )


def closeness(label: str, name: str, normalizer: Normalizer, lexicon: Lexicon) -> float:
    """How surely `label` and `name` name the same entity: 0 when their content words
    say otherwise, else the lower of the two run similarities."""
    mine = content_words(label, normalizer, lexicon)
    theirs = content_words(name, normalizer, lexicon)
    if not mine or not theirs or _distinct(mine, theirs, lexicon):
        return 0.0
    left, right = " ".join(mine), " ".join(theirs)
    return min(word_run_similarity(left, right), word_run_similarity(right, left))


def close_entity(
    label: str,
    names: list[tuple[UUID, str]],
    *,
    threshold: float,
    normalizer: Normalizer,
    lexicon: Lexicon,
) -> UUID | None:
    """The one entity of `names` ((entity, whole name) pairs) closest to `label` from
    `threshold`; None when none is, or when two entities are equally close."""
    best: dict[UUID, float] = {}
    for entity_id, name in names:
        score = closeness(label, name, normalizer, lexicon)
        if score >= threshold:
            best[entity_id] = max(best.get(entity_id, 0.0), score)
    ranked = sorted(best.items(), key=lambda item: item[1], reverse=True)
    if not ranked or (len(ranked) > 1 and ranked[1][1] == ranked[0][1]):
        return None
    return ranked[0][0]
