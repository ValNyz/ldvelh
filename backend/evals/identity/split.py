"""Stratified dev/test split of the identity corpus, by campaign (#151, spec § 3.3).

A **campaign** (`Scene.campaign`) groups the scenes that share a world or a history:
all turns of one real game, all scenes of one synthetic world, one issue family. A dev
scene's history holds the earlier narrations of its campaign with their reviewed links,
so splitting a campaign would show test gold on the dev side: the split moves whole
campaigns.

The objective is that every category's share of mentions in test is close to
`1 - ratio` (hard categories weigh more). Campaigns are assigned greedily in an order
shuffled with the seed, then improved by single moves and pairwise swaps until no move
lowers the objective; this is repeated from several shuffles and the best split kept.
The split is deterministic for a given corpus, ratio and seed; it is frozen with
TEST_SHA256 once the corpus is complete (D25).
"""

from __future__ import annotations

import random
from collections import Counter

from evals.identity.corpus import HARD_CATEGORIES, Scene, Split

CATEGORY_ORDER = (*HARD_CATEGORIES, "EASY", "PC", "SKIP")
HARD_WEIGHT = 4.0
RESTARTS = 16


def dominant_category(scene: Scene) -> str:
    counts = Counter(m.category for m in scene.gold)
    hard = [c for c in HARD_CATEGORIES if counts[c]]
    pool = hard or [c for c in CATEGORY_ORDER if counts[c]]
    if not pool:
        return "NONE"
    return max(pool, key=lambda c: (counts[c], -CATEGORY_ORDER.index(c)))


def _cost(test: Counter, totals: Counter, share: float) -> float:
    return sum(
        (HARD_WEIGHT if c in HARD_CATEGORIES else 1.0)
        * (test[c] / totals[c] - share) ** 2
        for c in totals
        if totals[c]
    )


def _greedy(order: list[str], counts: dict[str, Counter], share: float) -> set[str]:
    test, seen, chosen = Counter(), Counter(), set()
    for group in order:
        seen.update(counts[group])
        if _cost(test + counts[group], seen, share) < _cost(test, seen, share):
            test.update(counts[group])
            chosen.add(group)
    return chosen


def _improve(
    chosen: set[str], counts: dict[str, Counter], totals: Counter, share: float
) -> tuple[set[str], float]:
    """Single moves and dev/test swaps while one lowers the objective."""
    test = sum((counts[g] for g in chosen), Counter())
    best = _cost(test, totals, share)
    improved = True
    while improved:
        improved = False
        names = sorted(counts)
        moves = [((g,), ()) if g in chosen else ((), (g,)) for g in names]
        moves += [
            ((a,), (b,)) for a in sorted(chosen) for b in names if b not in chosen
        ]
        for out, into in moves:
            candidate = Counter(test)
            for g in out:
                candidate.subtract(counts[g])
            for g in into:
                candidate.update(counts[g])
            cost = _cost(candidate, totals, share)
            if cost < best - 1e-12:
                chosen = (chosen - set(out)) | set(into)
                test, best, improved = candidate, cost, True
                break
    return chosen, best


def stratified_split(scenes: list[Scene], *, ratio: float, seed: int) -> Split:
    """Dev gets about `ratio` of each category's mentions, test the rest; campaigns stay whole."""
    if not 0 < ratio < 1:
        raise ValueError(f"ratio must be in (0, 1), got {ratio}")
    share = 1 - ratio
    counts: dict[str, Counter] = {}
    members: dict[str, list[str]] = {}
    for scene in sorted(scenes, key=lambda s: s.id):
        counts.setdefault(scene.campaign, Counter()).update(
            m.category for m in scene.gold
        )
        members.setdefault(scene.campaign, []).append(scene.id)
    totals = sum(counts.values(), Counter())
    rng = random.Random(seed)
    best: tuple[float, set[str]] | None = None
    for _ in range(RESTARTS):
        order = sorted(counts)
        rng.shuffle(order)
        chosen, cost = _improve(_greedy(order, counts, share), counts, totals, share)
        if best is None or cost < best[0] - 1e-12:
            best = (cost, chosen)
    chosen = best[1] if best else set()
    test = sorted(i for g in chosen for i in members[g])
    dev = sorted(i for g in counts if g not in chosen for i in members[g])
    return Split(dev=dev, test=test)


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
