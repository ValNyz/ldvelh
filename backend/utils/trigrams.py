"""pg_trgm's similarity in Python, for code that compares names without the database."""

from __future__ import annotations

import re

_WORDS = re.compile(r"[^\W_]+")


def _trigrams(text: str) -> set[str]:
    grams = set()
    for word in _WORDS.findall(text.lower()):
        padded = f"  {word} "
        grams |= {padded[i : i + 3] for i in range(len(padded) - 2)}
    return grams


def trigram_similarity(a: str, b: str) -> float:
    """pg_trgm's similarity(): shared trigrams over all trigrams of the words of a and b
    (each word padded with two spaces before and one after)."""
    left, right = _trigrams(a), _trigrams(b)
    if not left or not right:
        return 0.0
    shared = len(left & right)
    return shared / (len(left) + len(right) - shared)


def word_run_similarity(a: str, b: str) -> float:
    """The best similarity() of a with a run of whole consecutive words of b, close to
    pg_trgm's strict_word_similarity (« Coopérative » in « Coopérative Agronomique »: 1)."""
    words = _WORDS.findall(b.lower())
    return max(
        (
            trigram_similarity(a, " ".join(words[i:j]))
            for i in range(len(words))
            for j in range(i + 1, len(words) + 1)
        ),
        default=0.0,
    )


def trigram_name_similarity(a: str, b: str) -> float:
    """How alike two names are: the best of their similarity() and of the run similarity
    of each inside the other. Symmetric, and broader than pg_trgm's word_similarity
    (repos.entities.name_similarity is the SQL one): « Keswil » and « Odran Keswil »
    score 1 either way round."""
    return max(
        trigram_similarity(a, b), word_run_similarity(a, b), word_run_similarity(b, a)
    )
