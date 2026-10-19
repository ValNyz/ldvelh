"""Per-mention scoring of identity decisions against the gold corpus (#151, spec § 3.4).

A scene is scored on its narration gold only (history mentions are context, never
scored). Decisions are aligned to gold mentions by `start`; a decision at a start with
no gold mention is ignored, since every measure is per gold mention (ANNOTATION § 13,
pronouns). What counts as correct, from ANNOTATION.md § 4.3 and § 5:

- the decision must equal `expected` or one of `accept_also`, in the same form:
  `MATCH <id>` needs the id; `ALIAS <id> <kind>` needs the id **and** the alias kind
  (a MATCH on an ALIAS gold leaves the name unrecorded, the Kethari failure; an ALIAS
  on a MATCH gold is right only when `accept_also` lists it); `NEW` needs the mention to
  be new, whatever `new_type` the system chose (spec § 3.4: "la mention est vraiment
  nouvelle");
- a SKIP gold ("à ne pas lier") is right when the system decides SKIP **or** emits no
  decision at that start; any link, NEW or UNSURE on it is wrong;
- a linked gold (MATCH, ALIAS, NEW) with no decision is wrong;
- UNSURE is wrong, except on a NEW trap (`trap: true`), where not merging is right.

Rates: `W` = MATCH/ALIAS to an id that no accepted form names, over all gold mentions
(a link on a NEW or SKIP gold is a wrong merge); `D` = NEW on a gold MATCH/ALIAS, over
those golds; NEW precision over the NEW decisions on gold mentions, recall over gold
NEW (UNSURE on a trap is right but is not a NEW); `C@10` = an accepted gold id among the
first 10 candidates of the mention, over gold MATCH/ALIAS; `unsure_rate` over gold
mentions; `deterministic_share` over the aligned decisions; `escalation_rate` = scenes
(turns) with an escalated decision over scenes; `cost` = summed `usage` counters plus
their per-turn means. The hard macro averages only the hard categories present.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Literal

from evals.identity.corpus import (
    HARD_CATEGORIES,
    Expected,
    GoldMention,
    Scene,
    parse_expected,
)

DecisionKind = Literal["MATCH", "ALIAS", "NEW", "UNSURE", "SKIP"]
EASY_POOL = ("EASY", "PC", "SKIP")
CANDIDATES_K = 10


@dataclass(frozen=True)
class Decision:
    surface: str
    start: int
    decision: DecisionKind
    entity_id: str | None
    alias_kind: str | None
    new_type: str | None
    deterministic: bool = False
    escalated: bool = False


@dataclass(frozen=True)
class RunResult:
    scene_id: str
    decisions: list[Decision]
    candidates: dict[int, list[str]]  # mention start -> candidate ids, best first
    usage: dict


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
    unsure: bool
    candidate_hit: bool | None  # None when the gold is not existing


@dataclass(frozen=True)
class SceneScore:
    scene_id: str
    outcomes: list[MentionOutcome]
    decisions: int
    deterministic: int
    escalated: bool
    usage: dict


@dataclass
class Metrics:
    by_category: dict[str, Acc]
    by_category_type: dict[tuple[str, str], Acc]
    hard_macro: float
    hard_pool: Acc
    easy_pool: Acc
    W: float
    D: float
    new_precision: float
    new_recall: float
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
        return True
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
    existing = m.parsed.decision in ("MATCH", "ALIAS")
    new_accepted = any(f.decision == "NEW" for f in forms)
    hit = None
    if existing:
        hit = bool(gold_ids & set((candidates or [])[:CANDIDATES_K]))
    return MentionOutcome(
        category=m.category,
        entity_type=_entity_type(scene, m.parsed),
        correct=_is_correct(m, decision),
        wrong_merge=kind in ("MATCH", "ALIAS") and decision.entity_id not in gold_ids,
        existing_gold=existing,
        duplicate=existing and kind == "NEW" and not new_accepted,
        new_gold=m.parsed.decision == "NEW",
        new_decided=kind == "NEW",
        unsure=kind == "UNSURE",
        candidate_hit=hit,
    )


# --- scene and corpus -------------------------------------------------------


def score_scene(scene: Scene, result: RunResult) -> SceneScore:
    if result.scene_id != scene.id:
        raise ValueError(f"result of {result.scene_id!r} scored against {scene.id!r}")
    by_start = {d.start: d for d in result.decisions}
    aligned = [by_start[m.start] for m in scene.gold if m.start in by_start]
    outcomes = [
        _outcome(scene, m, by_start.get(m.start), result.candidates.get(m.start))
        for m in scene.gold
    ]
    return SceneScore(
        scene_id=scene.id,
        outcomes=outcomes,
        decisions=len(aligned),
        deterministic=sum(d.deterministic for d in aligned),
        escalated=any(d.escalated for d in result.decisions),
        usage=dict(result.usage),
    )


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else math.nan


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
    present = [by_category[c].value for c in HARD_CATEGORIES if c in by_category]
    macro = sum(present) / len(present) if present else math.nan
    return dict(by_category), dict(by_type), macro, hard, easy


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
    by_category, by_type, macro, hard, easy = _accuracies(outcomes)
    existing = [o for o in outcomes if o.existing_gold]
    decided_new = [o for o in outcomes if o.new_decided]
    gold_new = [o for o in outcomes if o.new_gold]
    hits = [o.candidate_hit for o in existing]
    return Metrics(
        by_category=by_category,
        by_category_type=by_type,
        hard_macro=macro,
        hard_pool=hard,
        easy_pool=easy,
        W=_ratio(sum(o.wrong_merge for o in outcomes), len(outcomes)),
        D=_ratio(sum(o.duplicate for o in existing), len(existing)),
        new_precision=_ratio(sum(o.new_gold for o in decided_new), len(decided_new)),
        new_recall=_ratio(sum(o.new_decided for o in gold_new), len(gold_new)),
        c_at_10=_ratio(sum(bool(h) for h in hits), len(hits)),
        unsure_rate=_ratio(sum(o.unsure for o in outcomes), len(outcomes)),
        deterministic_share=_ratio(
            sum(s.deterministic for s in scores), sum(s.decisions for s in scores)
        ),
        escalation_rate=_ratio(sum(s.escalated for s in scores), len(scores)),
        cost=_cost(scores),
    )
