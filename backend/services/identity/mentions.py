"""Spans of a turn's mentions in the raw narration (spec §4.5.6, §4.9).

A decision names a surface; every whole-word occurrence of it in the text is a span,
compared case- and accent-insensitively (the pack's folding), with offsets in the raw
text; a prepass decision keeps to the occurrences written exactly like its surface (it
decided each written form on its own, another form may be another use). When the model
gave several decisions for one surface, each occurrence goes to the decision whose
`before` words precede it, and one an unlinked decision (UNSURE, SKIP) claims stays
unlinked. Occurrences of a surface several decisions share go to them in text order (the
prepass decides each occurrence on its own); a span overlapping a longer one already
taken is dropped, never moved.
"""

from __future__ import annotations

import re
from typing import TypeVar
from uuid import UUID

from domain.identity import DECISIONS, MentionDecision, MentionRow
from services.identity.normalize import Normalizer

MATCH, ALIAS, NEW, _, _ = DECISIONS
# entity_mentions.decision of a linked decision.
_STORED = {MATCH: "match", ALIAS: "alias", NEW: "new"}
DETERMINISTIC = "deterministic"
T = TypeVar("T")
_WORDS = re.compile(r"\w+")


def _folded_with_offsets(text: str, normalizer: Normalizer) -> tuple[str, list[int]]:
    """`text` folded character by character, and the raw index of each folded one."""
    pieces: list[str] = []
    origin: list[int] = []
    for i, ch in enumerate(text):
        folded = normalizer.fold(ch)
        pieces.append(folded)
        origin.extend([i] * len(folded))
    return "".join(pieces), origin


def find_spans(
    text: str, surface: str, normalizer: Normalizer
) -> list[tuple[int, int]]:
    """(start, end) in `text` of each whole-word occurrence of `surface`."""
    target = normalizer.fold(surface).split()
    if not target:
        return []
    folded, origin = _folded_with_offsets(text, normalizer)
    body = r"\s+".join(re.escape(word) for word in target)
    return [
        (origin[m.start()], origin[m.end() - 1] + 1)
        for m in re.finditer(rf"(?<!\w){body}(?!\w)", folded)
    ]


def stored_decision(d: MentionDecision) -> str:
    return DETERMINISTIC if d.deterministic else _STORED[d.decision]


def _preceding(text: str, start: int, count: int, normalizer: Normalizer) -> str:
    """The `count` words before `start`, folded."""
    if count <= 0:
        return ""
    words = _WORDS.findall(text[:start])[-count:]
    return " ".join(normalizer.fold(w) for w in words)


def _owners_of(
    spans: list[tuple[int, int]],
    owners: list[tuple[MentionDecision, T]],
    others: list[MentionDecision],
    text: str,
    normalizer: Normalizer,
) -> list[tuple[int, int, MentionDecision, T]]:
    """Each occurrence with the decision it belongs to. A single decision on a surface
    takes every occurrence. When several decisions share it (the model decided each
    occurrence, `others` holding those that link nothing), an occurrence goes to the
    decision whose `before` words precede it, an occurrence an unlinked decision claims
    goes to none, and the rest go to the linked decisions in text order."""
    if len(owners) + len(others) <= 1:
        d, item = owners[0]
        return [(s, e, d, item) for s, e in spans]
    claimants = [(d, (d, item)) for d, item in owners] + [(d, None) for d in others]
    context = [
        [normalizer.fold(w) for w in _WORDS.findall(d.before)] for d, _ in claimants
    ]
    unused = list(range(len(claimants)))
    placed, rest = [], []
    for s, e in spans:
        hit = next(
            (
                i
                for i in unused
                if context[i]
                and _preceding(text, s, len(context[i]), normalizer)
                == " ".join(context[i])
            ),
            None,
        )
        if hit is None:
            rest.append((s, e))
            continue
        unused.remove(hit)
        owner = claimants[hit][1]
        if owner is not None:
            placed.append((s, e, *owner))
    free = [claimants[i][1] for i in unused if claimants[i][1] is not None] or owners
    for rank, (s, e) in enumerate(rest):
        d, item = free[min(rank, len(free) - 1)]
        placed.append((s, e, d, item))
    return placed


def place(
    text: str,
    items: list[tuple[MentionDecision, T]],
    normalizer: Normalizer,
    others: list[MentionDecision] = (),
) -> list[tuple[int, int, MentionDecision, T]]:
    """(start, end, decision, item) of each span the decisions take in `text`, in text
    order (see the module docstring). `others`: the turn's decisions that link nothing
    (UNSURE, SKIP), whose occurrences a linked decision of the same surface must leave."""
    by_surface: dict[tuple[bool, str], list[tuple[MentionDecision, T]]] = {}
    for d, item in items:
        # A prepass decision decided one written form: it keeps to that exact form.
        key = d.surface if d.deterministic else normalizer.fold(d.surface).strip()
        by_surface.setdefault((not d.deterministic, key), []).append((d, item))
    unlinked: dict[str, list[MentionDecision]] = {}
    for d in others:
        unlinked.setdefault(normalizer.fold(d.surface).strip(), []).append(d)
    candidates = []
    # Prepass groups first: at equal length, the decided occurrence keeps its decision.
    for (model, key), owners in sorted(by_surface.items(), key=lambda g: g[0][0]):
        spans = find_spans(text, owners[0][0].surface, normalizer)
        if not model:
            spans = [(s, e) for s, e in spans if text[s:e] == key]
            candidates += _owners_of(spans, owners, [], text, normalizer)
            continue
        candidates += _owners_of(spans, owners, unlinked.get(key, []), text, normalizer)
    taken: list[tuple[int, int]] = []
    placed = []
    # Longest spans first: « le Vieux Moulin » keeps its span over « Moulin ».
    for start, end, d, item in sorted(candidates, key=lambda c: c[0] - c[1]):
        if any(start < e and s < end for s, e in taken):
            continue
        taken.append((start, end))
        placed.append((start, end, d, item))
    return sorted(placed, key=lambda p: p[0])


def mention_rows(
    text: str,
    linked: list[tuple[MentionDecision, UUID]],
    normalizer: Normalizer,
    others: list[MentionDecision] = (),
) -> list[MentionRow]:
    """The entity_mentions rows of the linked decisions, in text order (`others`: the
    decisions that link nothing, see `place`)."""
    return [
        MentionRow(
            start_pos=start,
            end_pos=end,
            surface=text[start:end],
            entity_id=entity_id,
            decision=stored_decision(d),
            evidence=d.evidence or None,
        )
        for start, end, d, entity_id in place(text, linked, normalizer, others)
    ]
