"""Confidence intervals by bootstrap over scenes (#151, spec § 3.5).

The mentions of a scene are correlated, so the resampling unit is the scene: each
iteration draws as many scenes as there are, with replacement, and recomputes the
metric on them. The interval is the 2.5 / 97.5 percentile of the replicates.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable, Sequence
from typing import TypeVar

T = TypeVar("T")

LOW_PERCENTILE, HIGH_PERCENTILE = 2.5, 97.5


def _percentile(sorted_values: list[float], percent: float) -> float:
    """Linear interpolation between closest ranks (numpy's default method)."""
    position = (len(sorted_values) - 1) * percent / 100
    low = math.floor(position)
    high = min(low + 1, len(sorted_values) - 1)
    weight = position - low
    return sorted_values[low] * (1 - weight) + sorted_values[high] * weight


def ci(
    scores: Sequence[T],
    metric: Callable[[list[T]], float],
    *,
    iterations: int = 2000,
    seed: int = 0,
) -> tuple[float, float]:
    """95 % interval of `metric` by resampling `scores` per scene; (nan, nan) if undefined.

    Replicates where the metric is undefined (nan: e.g. no mention of the category in
    the draw) are dropped.
    """
    if not scores:
        return math.nan, math.nan
    rng = random.Random(seed)
    pool = list(scores)
    replicates = []
    for _ in range(iterations):
        value = metric(rng.choices(pool, k=len(pool)))
        if not math.isnan(value):
            replicates.append(value)
    if not replicates:
        return math.nan, math.nan
    replicates.sort()
    return (
        _percentile(replicates, LOW_PERCENTILE),
        _percentile(replicates, HIGH_PERCENTILE),
    )
