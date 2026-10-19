"""Stratified dev/test split of the identity corpus (#151, spec § 3.3).

Each scene is stratified by its **dominant category**: the hard category with the most
gold mentions (ties broken by the order of HARD_CATEGORIES), else its most frequent
category. Strata are visited in a fixed order and their scenes shuffled with the seed;
each scene then goes to the side that keeps every category's test share of mentions
closest to `1 - ratio` (a greedy balance on the running counts). A scene-level split
alone could not hold the mention shares: scenes carry several categories each.

The split is deterministic for a given corpus, ratio and seed; it is regenerated while
the corpus grows and frozen with TEST_SHA256 once the corpus is complete (D25).
"""

from __future__ import annotations

import random
from collections import Counter

from evals.identity.corpus import HARD_CATEGORIES, Scene, Split

CATEGORY_ORDER = (*HARD_CATEGORIES, "EASY", "PC", "SKIP")


def dominant_category(scene: Scene) -> str:
    counts = Counter(m.category for m in scene.gold)
    hard = [c for c in HARD_CATEGORIES if counts[c]]
    pool = hard or [c for c in CATEGORY_ORDER if counts[c]]
    if not pool:
        return "NONE"
    return max(pool, key=lambda c: (counts[c], -CATEGORY_ORDER.index(c)))


def _deviation(test: Counter, seen: Counter, share: float) -> float:
    return sum((test[c] - share * seen[c]) ** 2 for c in seen)


def stratified_split(scenes: list[Scene], *, ratio: float, seed: int) -> Split:
    """Dev gets about `ratio` of each category's mentions, test the rest."""
    if not 0 < ratio < 1:
        raise ValueError(f"ratio must be in (0, 1), got {ratio}")
    share = 1 - ratio
    rng = random.Random(seed)
    strata: dict[str, list[Scene]] = {}
    for scene in sorted(scenes, key=lambda s: s.id):
        strata.setdefault(dominant_category(scene), []).append(scene)
    order = [c for c in (*CATEGORY_ORDER, "NONE") if c in strata]
    test_counts, seen = Counter(), Counter()
    dev, test = [], []
    for category in order:
        members = strata[category]
        rng.shuffle(members)
        for scene in members:
            counts = Counter(m.category for m in scene.gold)
            seen.update(counts)
            to_test = test_counts + counts
            if _deviation(to_test, seen, share) < _deviation(test_counts, seen, share):
                test_counts = to_test
                test.append(scene.id)
            else:
                dev.append(scene.id)
    return Split(dev=sorted(dev), test=sorted(test))


def shares_in_test(scenes: list[Scene], split: Split) -> dict[str, tuple[int, int]]:
    """Per category: (mentions in test, mentions in the corpus)."""
    test_ids = set(split.test)
    totals, in_test = Counter(), Counter()
    for scene in scenes:
        counts = Counter(m.category for m in scene.gold)
        totals.update(counts)
        if scene.id in test_ids:
            in_test.update(counts)
    return {c: (in_test[c], totals[c]) for c in CATEGORY_ORDER if totals[c]}
