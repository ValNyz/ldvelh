"""Confidence intervals by bootstrap over scenes (#151, spec § 3.5).

The mentions of a scene are correlated, and so are the runs of one scene (spec § 3.5:
the 3 runs are not independent), so the resampling unit is the scene: the scores are
grouped by `key` (the scene id by default), each iteration draws as many groups as
there are, with replacement, and recomputes the metric on the members of the drawn
groups. The interval is the 2.5 / 97.5 percentile of the replicates.

Callers with several runs (the eval runner and report) pass the pooled `SceneScore`s
of every run in one list, with the default key: `ci(run1 + run2 + run3, metric)`. They
must not bootstrap each run apart, nor give each score its own key, which would treat
the runs of a scene as independent draws and narrow the interval about sqrt(3) times.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable, Sequence
from typing import Any, TypeVar

T = TypeVar("T")


def _scene_id(score: Any) -> Any:
    return score.scene_id


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
    key: Callable[[T], Any] = _scene_id,
) -> tuple[float, float]:
    """95 % interval of `metric`, resampling whole groups of `key`; (nan, nan) if undefined.

    Replicates where the metric is undefined (nan: e.g. no mention of the category in
    the draw) are dropped.
    """
    if not scores:
        return math.nan, math.nan
    rng = random.Random(seed)
    groups: dict[Any, list[T]] = {}
    for score in scores:
        groups.setdefault(key(score), []).append(score)
    pool = list(groups.values())
    replicates = []
    for _ in range(iterations):
        drawn = rng.choices(pool, k=len(pool))
        value = metric([score for group in drawn for score in group])
        if not math.isnan(value):
            replicates.append(value)
    if not replicates:
        return math.nan, math.nan
    replicates.sort()
    return (
        _percentile(replicates, LOW_PERCENTILE),
        _percentile(replicates, HIGH_PERCENTILE),
    )
