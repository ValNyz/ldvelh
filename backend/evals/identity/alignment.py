"""Alignment of system decisions to gold mentions (#151).

The resolver does not have to reproduce the corpus boundary rules (ANNOTATION § 4.2:
determiner included, contracted preposition excluded), so a decision is aligned to a
gold mention in three passes, each over the decisions still unaligned:

1. same `start`;
2. same end offset, when exactly one gold mention ends there, it is still free and the
   spans really overlap ("Kethari âgée" for gold "La Kethari âgée"; nested mentions can
   share an end, hence the uniqueness check; an empty surface never aligns here);
3. a free gold span that contains the non-empty decision span and holds no other gold
   mention overlapping it (the innermost mention that covers the decision).

A gold mention takes at most one decision; the decisions left over are spurious.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from evals.identity.corpus import GoldMention
    from evals.identity.run import Decision


class Alignment(NamedTuple):
    by_gold: dict[int, Decision]  # gold mention start -> its decision
    spurious: list[Decision]


def _end(m: GoldMention) -> int:
    return m.start + len(m.surface)


def overlaps(m: GoldMention, d: Decision) -> bool:
    """The spans share at least one character (an empty span overlaps nothing)."""
    return max(m.start, d.start) < min(_end(m), d.end)


def _check_unique_starts(decisions: list[Decision]) -> None:
    counts = Counter(d.start for d in decisions)
    duplicates = sorted(s for s, n in counts.items() if n > 1)
    if duplicates:
        raise ValueError(f"several decisions at start {duplicates[0]}")


def _container(
    mentions: list[GoldMention], d: Decision, taken: dict[int, Decision]
) -> GoldMention | None:
    def holds_an_overlapping_mention(g: GoldMention) -> bool:
        return any(
            h is not g
            and g.start <= h.start
            and _end(h) <= _end(g)
            and h.start < d.end
            and d.start < _end(h)
            for h in mentions
        )

    found = [
        g
        for g in mentions
        if g.start not in taken
        and d.start < d.end
        and g.start <= d.start
        and d.end <= _end(g)
        and not holds_an_overlapping_mention(g)
    ]
    return found[0] if len(found) == 1 else None


def align(mentions: list[GoldMention], decisions: list[Decision]) -> Alignment:
    """Raises ValueError when two decisions share a start (no silent last-wins)."""
    _check_unique_starts(decisions)
    starts = {m.start for m in mentions}
    by_gold = {d.start: d for d in decisions if d.start in starts}
    rest = [d for d in decisions if d.start not in starts]
    by_end: dict[int, list[GoldMention]] = defaultdict(list)
    for m in mentions:
        by_end[_end(m)].append(m)
    leftover = []
    for d in rest:
        same_end = by_end.get(d.end, [])
        if (
            len(same_end) == 1
            and same_end[0].start not in by_gold
            and overlaps(same_end[0], d)
        ):
            by_gold[same_end[0].start] = d
        else:
            leftover.append(d)
    spurious = []
    for d in leftover:
        target = _container(mentions, d, by_gold)
        if target is None:
            spurious.append(d)
        else:
            by_gold[target.start] = d
    return Alignment(by_gold, spurious)
