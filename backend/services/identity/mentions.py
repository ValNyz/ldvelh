"""Spans of a turn's mentions in the raw narration (spec §4.5.6, §4.9).

A decision names a surface; every whole-word occurrence of it in the text is a span,
compared case- and accent-insensitively (the pack's folding), with offsets in the raw
text. Occurrences of a surface several decisions share go to them in text order (the
prepass decides each occurrence on its own); a span overlapping a longer one already
taken is dropped, never moved.
"""

from __future__ import annotations

import re
from uuid import UUID

from domain.identity import DECISIONS, MentionDecision, MentionRow
from services.identity.normalize import Normalizer

MATCH, ALIAS, NEW, _, _ = DECISIONS
# entity_mentions.decision of a linked decision.
_STORED = {MATCH: "match", ALIAS: "alias", NEW: "new"}
DETERMINISTIC = "deterministic"


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


def mention_rows(
    text: str, linked: list[tuple[MentionDecision, UUID]], normalizer: Normalizer
) -> list[MentionRow]:
    """The entity_mentions rows of the linked decisions, in text order."""
    by_surface: dict[str, list[tuple[MentionDecision, UUID]]] = {}
    for d, entity_id in linked:
        by_surface.setdefault(normalizer.fold(d.surface).strip(), []).append(
            (d, entity_id)
        )
    candidates = []
    for owners in by_surface.values():
        spans = find_spans(text, owners[0][0].surface, normalizer)
        for rank, (start, end) in enumerate(spans):
            d, entity_id = owners[min(rank, len(owners) - 1)]
            candidates.append((start, end, d, entity_id))
    taken: list[tuple[int, int]] = []
    rows = []
    # Longest spans first: « le Vieux Moulin » keeps its span over « Moulin ».
    for start, end, d, entity_id in sorted(candidates, key=lambda c: c[0] - c[1]):
        if any(start < e and s < end for s, e in taken):
            continue
        taken.append((start, end))
        rows.append(
            MentionRow(
                start_pos=start,
                end_pos=end,
                surface=text[start:end],
                entity_id=entity_id,
                decision=stored_decision(d),
                evidence=d.evidence or None,
            )
        )
    return sorted(rows, key=lambda r: r.start_pos)
