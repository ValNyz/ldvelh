"""Coreference metrics on sequences: B³ and CEAF-e, without dependency (#151, spec § 3.4).

Clusters are `{cluster id: set of mention keys}` (keys `<scene id>:<start>`, as in
`gold_clusters`); cluster ids are free and never compared. Mentions present on one
side only are allowed: B³ precision is averaged over the system mentions, recall over
the gold mentions, and a mention missing from the other side shares nothing with it.
CEAF-e aligns gold and system clusters one-to-one with the entity similarity
phi4(K, R) = 2 |K ∩ R| / (|K| + |R|), maximised by a local Kuhn-Munkres.
"""

from __future__ import annotations

import math

Clusters = dict[str, set[str]]


def _f1(precision: float, recall: float) -> float:
    total = precision + recall
    return 2 * precision * recall / total if total else 0.0


def _b_cubed_side(key: Clusters, response: Clusters) -> float:
    """Mean over the mentions of `key` of |key cluster ∩ response cluster| / |key cluster|."""
    owner = {mention: cid for cid, cluster in response.items() for mention in cluster}
    shares, count = 0.0, 0
    for cluster in key.values():
        for mention in cluster:
            other = response.get(owner.get(mention, ""), set())
            shares += len(cluster & other) / len(cluster)
            count += 1
    return shares / count if count else 0.0


def b_cubed(gold: Clusters, system: Clusters) -> tuple[float, float, float]:
    precision = _b_cubed_side(system, gold)
    recall = _b_cubed_side(gold, system)
    return precision, recall, _f1(precision, recall)


def _phi4(a: set[str], b: set[str]) -> float:
    return 2 * len(a & b) / (len(a) + len(b)) if a or b else 0.0


def max_weight_assignment(weights: list[list[float]]) -> list[tuple[int, int]]:
    """Row/column pairs of a maximum-weight one-to-one matching (Kuhn-Munkres, O(n³)).

    `weights` is rectangular (rows x columns, every row the same length); it is padded to
    a square with zeros, and pairs on padding are dropped.
    """
    rows = len(weights)
    cols = len(weights[0]) if rows else 0
    n = max(rows, cols)
    if n == 0:
        return []
    top = max((w for row in weights for w in row), default=0.0)

    def cost(i: int, j: int) -> float:  # minimisation on 1-based indices
        inside = i <= rows and j <= cols
        return top - (weights[i - 1][j - 1] if inside else 0.0)

    u, v = [0.0] * (n + 1), [0.0] * (n + 1)
    match = [0] * (n + 1)  # match[column] = row
    way = [0] * (n + 1)
    for i in range(1, n + 1):
        match[0], j0 = i, 0
        slack, used = [math.inf] * (n + 1), [False] * (n + 1)
        while match[j0]:
            used[j0] = True
            i0, delta, j1 = match[j0], math.inf, 0
            for j in range(1, n + 1):
                if used[j]:
                    continue
                reduced = cost(i0, j) - u[i0] - v[j]
                if reduced < slack[j]:
                    slack[j], way[j] = reduced, j0
                if slack[j] < delta:
                    delta, j1 = slack[j], j
            for j in range(n + 1):
                if used[j]:
                    u[match[j]] += delta
                    v[j] -= delta
                else:
                    slack[j] -= delta
            j0 = j1
        while j0:
            j1 = way[j0]
            match[j0] = match[j1]
            j0 = j1
    return [
        (match[j] - 1, j - 1) for j in range(1, n + 1) if match[j] <= rows and j <= cols
    ]


def ceaf_e(gold: Clusters, system: Clusters) -> float:
    """Entity-based CEAF F1 (phi4)."""
    keys, responses = list(gold.values()), list(system.values())
    if not keys or not responses:
        return 0.0
    weights = [[_phi4(k, r) for r in responses] for k in keys]
    total = sum(weights[i][j] for i, j in max_weight_assignment(weights))
    return _f1(total / len(responses), total / len(keys))
