"""Per-mention scoring of identity decisions against the gold corpus (#151, spec § 3.4).

A scene is scored on its narration gold only (history mentions are context, never
scored). Decisions are aligned to gold mentions by span (evals/identity/alignment.py:
same start, then same end, then containment); two decisions at one start are an error.
What counts as correct, from ANNOTATION.md § 4.3 and § 5:

- the decision must equal `expected` or one of `accept_also`, in the same form:
  `MATCH <id>` needs the id; `ALIAS <id> <kind>` needs the id **and** the alias kind
  (a MATCH on an ALIAS gold leaves the name unrecorded, the Kethari failure; an ALIAS
  on a MATCH gold is right only when `accept_also` lists it); `NEW <type>` needs the
  type too (the created stub's type drives the graph; a wrong type is counted apart in
  `new_type_errors`);
- a SKIP gold ("à ne pas lier") is right when the system decides SKIP **or** emits no
  decision on it; any link, NEW or UNSURE on it is wrong;
- a linked gold (MATCH, ALIAS, NEW) with no decision is wrong;
- UNSURE is wrong, except on a NEW trap (`trap: true`), where not merging is right.

Decisions aligned to no gold mention are **spurious**, reported per turn
(`spurious_link_per_turn`, `spurious_new_per_turn`). A spurious MATCH/ALIAS is a wrong
merge only when it **conflicts** with the gold: its span overlaps gold mentions and none
of them accepts its id (the second half of a split name sent to another entity). A
spurious link that overlaps nothing (a personal pronoun, which ANNOTATION § 13 does not
count) or overlaps a mention of its own entity (a split name, or a nested mention of
that entity inside an enclosing SKIP) is not. A spurious NEW is a false NEW, and a
duplicate when it overlaps a gold MATCH/ALIAS. SKIP and UNSURE left over are ignored
(nothing linked, nothing created).

Rates: `W` = MATCH/ALIAS to an id that no accepted form names, on gold mentions plus the
conflicting spurious links, over the gold mentions (a link on a NEW or SKIP gold is a
wrong merge); `D` = NEW on a gold MATCH/ALIAS plus the spurious NEW overlapping one,
over those golds; NEW precision over every NEW decision
(aligned or spurious) and recall over gold NEW, both type-agnostic (NIL detection;
UNSURE on a trap is right but is not a NEW); `C@10` = an accepted gold id among the
first 10 candidates of the mention (looked up by gold start, then by the aligned
decision's start), over gold MATCH/ALIAS; `unsure_rate` over gold mentions;
`deterministic_share` over the aligned decisions; `escalation_rate` = scenes (turns)
with an escalated decision over scenes; `cost` = summed `usage` counters plus their
per-turn means. `hard_macro` is nan unless all six hard categories are present
(`hard_categories_missing` names the absent ones, `hard_macro_present` averages the
present ones).
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field

from evals.identity.alignment import align, overlaps
from evals.identity.corpus import (
    HARD_CATEGORIES,
    Expected,
    GoldMention,
    Scene,
    parse_expected,
)
from evals.identity.run import Decision, RunResult

EASY_POOL = ("EASY", "PC", "SKIP")
CANDIDATES_K = 10
LINKS = ("MATCH", "ALIAS")

__all__ = ["Decision", "RunResult", "aggregate", "score_scene"]


@dataclass
class Acc:
    correct: int = 0
    total: int = 0

    @property
    def value(self) -> float:
        return self.correct / self.total if self.total else math.nan

    def add(self, ok: bool) -> None:
        self.correct += ok
        self.total += 1


@dataclass(frozen=True)
class MentionOutcome:
    category: str
    entity_type: str  # target type, NEW type, or "none" for SKIP
    correct: bool
    wrong_merge: bool
    existing_gold: bool  # gold MATCH/ALIAS
    duplicate: bool
    new_gold: bool
    new_decided: bool
    new_type_error: bool  # NEW on a gold NEW, with another type
    unsure: bool
    candidate_hit: bool | None  # None when the gold is not existing


@dataclass(frozen=True)
class SceneScore:
    scene_id: str
    outcomes: list[MentionOutcome]
    decisions: int  # aligned decisions
    deterministic: int
    escalated: bool
    usage: dict
    spurious_new: int = 0
    spurious_links: int = 0  # unaligned MATCH/ALIAS
    spurious_wrong_merges: int = 0  # spurious links conflicting with the gold
    spurious_duplicates: int = 0  # spurious NEW overlapping a gold MATCH/ALIAS


@dataclass
class Metrics:
    by_category: dict[str, Acc]
    by_category_type: dict[tuple[str, str], Acc]
    hard_macro: float
    hard_macro_present: float
    hard_categories_missing: tuple[str, ...]
    hard_pool: Acc
    easy_pool: Acc
    W: float
    D: float
    new_precision: float
    new_recall: float
    new_type_errors: int
    spurious_new_per_turn: float
    spurious_link_per_turn: float
    c_at_10: float
    unsure_rate: float
    deterministic_share: float
    escalation_rate: float
    cost: dict[str, float] = field(default_factory=dict)


# --- one mention ------------------------------------------------------------


def _accepted(m: GoldMention) -> list[Expected]:
    return [m.parsed, *(parse_expected(text) for text in m.accept_also)]


def _matches(decision: Decision | None, form: Expected) -> bool:
    if form.decision == "SKIP":
        return decision is None or decision.decision == "SKIP"
    if decision is None or decision.decision != form.decision:
        return False
    if form.decision == "NEW":
        return decision.new_type == form.new_type
    if decision.entity_id != form.entity_id:
        return False
    return form.decision == "MATCH" or decision.alias_kind == form.alias_kind


def _is_correct(m: GoldMention, decision: Decision | None) -> bool:
    if decision is not None and decision.decision == "UNSURE":
        return m.trap
    return any(_matches(decision, form) for form in _accepted(m))


def _entity_type(scene: Scene, form: Expected) -> str:
    if form.decision == "NEW":
        return form.new_type or "none"
    entity = next((e for e in scene.world if e.id == form.entity_id), None)
    return entity.type if entity is not None else "none"


def _outcome(
    scene: Scene,
    m: GoldMention,
    decision: Decision | None,
    candidates: list[str] | None,
) -> MentionOutcome:
    forms = _accepted(m)
    gold_ids = {f.entity_id for f in forms if f.entity_id is not None}
    kind = decision.decision if decision is not None else None
    existing = m.parsed.decision in LINKS
    new_gold = m.parsed.decision == "NEW"
    hit = None
    if existing:
        hit = bool(gold_ids & set((candidates or [])[:CANDIDATES_K]))
    return MentionOutcome(
        category=m.category,
        entity_type=_entity_type(scene, m.parsed),
        correct=_is_correct(m, decision),
        wrong_merge=kind in LINKS and decision.entity_id not in gold_ids,
        existing_gold=existing,
        duplicate=existing and kind == "NEW",
        new_gold=new_gold,
        new_decided=kind == "NEW",
        new_type_error=new_gold
        and kind == "NEW"
        and decision.new_type != m.parsed.new_type,
        unsure=kind == "UNSURE",
        candidate_hit=hit,
    )


# --- scene and corpus -------------------------------------------------------


def _candidates(result: RunResult, m: GoldMention, d: Decision | None):
    found = result.candidates.get(m.start)
    if found is None and d is not None:
        found = result.candidates.get(d.start)
    return found


def score_scene(scene: Scene, result: RunResult) -> SceneScore:
    if result.scene_id != scene.id:
        raise ValueError(f"result of {result.scene_id!r} scored against {scene.id!r}")
    alignment = align(scene.gold, result.decisions)
    by_gold = alignment.by_gold
    outcomes = []
    for m in scene.gold:
        d = by_gold.get(m.start)
        outcomes.append(_outcome(scene, m, d, _candidates(result, m, d)))
    aligned = list(by_gold.values())
    links = [d for d in alignment.spurious if d.decision in LINKS]
    new = [d for d in alignment.spurious if d.decision == "NEW"]
    return SceneScore(
        scene_id=scene.id,
        outcomes=outcomes,
        decisions=len(aligned),
        deterministic=sum(d.deterministic for d in aligned),
        escalated=any(d.escalated for d in result.decisions),
        usage=dict(result.usage),
        spurious_new=len(new),
        spurious_links=len(links),
        spurious_wrong_merges=sum(_conflicts(scene.gold, d) for d in links),
        spurious_duplicates=sum(_on_existing_gold(scene.gold, d) for d in new),
    )


def _conflicts(mentions: list[GoldMention], d: Decision) -> bool:
    """A spurious link overlapping gold mentions, none of which accepts its id."""
    hit = [m for m in mentions if overlaps(m, d)]
    accepting = [m for m in hit if d.entity_id in {f.entity_id for f in _accepted(m)}]
    return d.entity_id is not None and bool(hit) and not accepting


def _on_existing_gold(mentions: list[GoldMention], d: Decision) -> bool:
    return any(m.parsed.decision in LINKS and overlaps(m, d) for m in mentions)


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else math.nan


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else math.nan


def _accuracies(outcomes: list[MentionOutcome]):
    by_category: dict[str, Acc] = defaultdict(Acc)
    by_type: dict[tuple[str, str], Acc] = defaultdict(Acc)
    hard, easy = Acc(), Acc()
    for o in outcomes:
        by_category[o.category].add(o.correct)
        by_type[(o.category, o.entity_type)].add(o.correct)
        if o.category in HARD_CATEGORIES:
            hard.add(o.correct)
        elif o.category in EASY_POOL:
            easy.add(o.correct)
    return dict(by_category), dict(by_type), hard, easy


def _cost(scores: list[SceneScore]) -> dict[str, float]:
    totals: dict[str, float] = defaultdict(float)
    for s in scores:
        for key, value in s.usage.items():
            if isinstance(value, int | float) and not isinstance(value, bool):
                totals[key] += value
    per_turn = {f"per_turn_{k}": v / len(scores) for k, v in totals.items()}
    return {**totals, **per_turn}


def aggregate(scores: list[SceneScore]) -> Metrics:
    outcomes = [o for s in scores for o in s.outcomes]
    by_category, by_type, hard, easy = _accuracies(outcomes)
    missing = tuple(c for c in HARD_CATEGORIES if c not in by_category)
    present = _mean([by_category[c].value for c in HARD_CATEGORIES if c in by_category])
    existing = [o for o in outcomes if o.existing_gold]
    gold_new = [o for o in outcomes if o.new_gold]
    spurious_new = sum(s.spurious_new for s in scores)
    wrong_merges = sum(o.wrong_merge for o in outcomes) + sum(
        s.spurious_wrong_merges for s in scores
    )
    hits = [o.candidate_hit for o in existing]
    return Metrics(
        by_category=by_category,
        by_category_type=by_type,
        hard_macro=math.nan if missing else present,
        hard_macro_present=present,
        hard_categories_missing=missing,
        hard_pool=hard,
        easy_pool=easy,
        W=_ratio(wrong_merges, len(outcomes)),
        D=_ratio(
            sum(o.duplicate for o in existing)
            + sum(s.spurious_duplicates for s in scores),
            len(existing),
        ),
        new_precision=_ratio(
            sum(o.new_gold and o.new_decided for o in outcomes),
            sum(o.new_decided for o in outcomes) + spurious_new,
        ),
        new_recall=_ratio(sum(o.new_decided for o in gold_new), len(gold_new)),
        new_type_errors=sum(o.new_type_error for o in outcomes),
        spurious_new_per_turn=_ratio(spurious_new, len(scores)),
        spurious_link_per_turn=_ratio(
            sum(s.spurious_links for s in scores), len(scores)
        ),
        c_at_10=_ratio(sum(bool(h) for h in hits), len(hits)),
        unsure_rate=_ratio(sum(o.unsure for o in outcomes), len(outcomes)),
        deterministic_share=_ratio(
            sum(s.deterministic for s in scores), sum(s.decisions for s in scores)
        ),
        escalation_rate=_ratio(sum(s.escalated for s in scores), len(scores)),
        cost=_cost(scores),
    )
