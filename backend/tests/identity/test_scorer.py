"""Identity scorer, per-scene bootstrap and coreference metrics (#151)."""

import math

import pytest

from evals.identity import bootstrap, coref
from evals.identity.corpus import Scene
from evals.identity.scorer import Decision, RunResult, aggregate, score_scene

WORLD = [
    {"id": "protagonist_val", "type": "protagonist", "label": "Val", "known": True,
     "true_name": "Val"},
    {"id": "character_nahle", "type": "character", "label": "La Kethari âgée",
     "known": False},
    {"id": "character_tesk", "type": "character", "label": "Tesk", "known": True,
     "true_name": "Tesk"},
    {"id": "location_cantine", "type": "location", "label": "Cantine", "known": True},
]  # fmt: skip


def _mention(start, category, expected, **extra) -> dict:
    return {"surface": f"m{start}", "start": start, "category": category,
            "expected": expected, **extra}  # fmt: skip


def _scene(gold: list[dict], scene_id: str = "s1") -> Scene:
    return Scene.model_validate(
        {
            "id": scene_id,
            "genre": "sf",
            "source": "synthetic",
            "world": WORLD,
            "history": [],
            "scene": {
                "location": "",
                "present": [],
                "reveals": [],
                "planned_npcs": [],
                "secrets": [],
                "open_disclosures": [],
            },
            "narration": "x" * 200,
            "gold": gold,
            "gold_effects": {"reveals": [], "merges": [], "forbidden_merges": []},
            "gold_knowledge": [],
        }
    )


def _d(start, decision, entity_id=None, kind=None, new_type=None, **flags) -> Decision:
    return Decision(f"m{start}", start, decision, entity_id, kind, new_type, **flags)


def _run(scene: Scene, decisions, candidates=None, usage=None) -> RunResult:
    return RunResult(scene.id, list(decisions), candidates or {}, usage or {})


def _metrics(gold, decisions, **run):
    scene = _scene(gold)
    return aggregate([score_scene(scene, _run(scene, decisions, **run))])


def test_match_to_wrong_id_counts_as_wrong_merge():
    gold = [
        _mention(0, "DESC", "MATCH character_nahle"),
        _mention(10, "EASY", "MATCH character_tesk"),
        _mention(20, "SKIP", "SKIP"),
        _mention(30, "NEW", "NEW character"),
    ]
    decisions = [
        _d(0, "MATCH", "character_tesk"),  # wrong id: a wrong merge
        _d(10, "MATCH", "character_tesk"),
        _d(20, "SKIP"),
        _d(30, "NEW", new_type="character"),
    ]
    m = _metrics(gold, decisions)
    assert m.W == pytest.approx(1 / 4)
    assert m.by_category["DESC"].value == 0.0
    # a link on a NEW gold is a wrong merge too (any id is wrong)
    m = _metrics(gold, decisions[:3] + [_d(30, "ALIAS", "character_tesk", "short")])
    assert m.W == pytest.approx(2 / 4)


def test_new_on_existing_gold_counts_as_duplicate():
    gold = [
        _mention(0, "DESC", "MATCH character_nahle"),
        _mention(10, "EASY", "MATCH character_tesk"),
        _mention(20, "NEW", "NEW location"),
    ]
    decisions = [
        _d(0, "NEW", new_type="character"),
        _d(10, "MATCH", "character_tesk"),
        _d(20, "NEW", new_type="location"),
    ]
    m = _metrics(gold, decisions)
    assert m.D == pytest.approx(1 / 2)  # over the existing golds only
    assert m.W == 0.0
    assert m.new_precision == pytest.approx(1 / 2)
    assert m.new_recall == 1.0


def test_unsure_is_wrong_except_on_a_trap():
    gold = [
        _mention(0, "NEW", "NEW character", trap=True),
        _mention(10, "NEW", "NEW character"),
        _mention(20, "DESC", "MATCH character_nahle"),
    ]
    decisions = [_d(0, "UNSURE"), _d(10, "UNSURE"), _d(20, "UNSURE")]
    m = _metrics(gold, decisions)
    assert m.by_category["NEW"].correct == 1
    assert m.by_category["NEW"].total == 2
    assert m.by_category["DESC"].value == 0.0
    assert m.unsure_rate == 1.0
    assert m.W == 0.0 and m.D == 0.0
    assert m.new_recall == 0.0  # recall counts NEW decisions only


def test_accept_also_is_accepted():
    gold = [
        _mention(0, "DESC", "MATCH character_nahle",
                 accept_also=["ALIAS character_nahle descriptor"]),
        _mention(10, "DESC", "MATCH character_nahle",
                 accept_also=["ALIAS character_nahle descriptor"]),
        _mention(20, "PART", "ALIAS character_nahle short",
                 accept_also=["MATCH character_nahle"]),
    ]  # fmt: skip
    decisions = [
        _d(0, "ALIAS", "character_nahle", "descriptor"),
        _d(10, "MATCH", "character_nahle"),
        _d(20, "MATCH", "character_nahle"),
    ]
    m = _metrics(gold, decisions)
    assert m.by_category["DESC"].value == 1.0
    assert m.by_category["PART"].value == 1.0


def test_alias_needs_the_right_kind():
    gold = [
        _mention(0, "REVEAL", "ALIAS character_nahle true_name"),
        _mention(10, "PART", "ALIAS character_nahle short"),
        _mention(20, "DESC", "MATCH character_nahle"),
    ]
    decisions = [
        _d(0, "ALIAS", "character_nahle", "descriptor"),  # right id, wrong kind
        _d(10, "MATCH", "character_nahle"),  # ALIAS gold: a MATCH does not record it
        _d(20, "ALIAS", "character_nahle", "descriptor"),  # not in accept_also
    ]
    m = _metrics(gold, decisions)
    assert m.by_category["REVEAL"].value == 0.0
    assert m.by_category["PART"].value == 0.0
    assert m.by_category["DESC"].value == 0.0
    assert m.W == 0.0  # right id everywhere: not a wrong merge


def test_skip_gold_is_right_without_a_decision_and_wrong_when_linked():
    gold = [
        _mention(0, "SKIP", "SKIP"),
        _mention(10, "SKIP", "SKIP"),
        _mention(20, "SKIP", "SKIP"),
        _mention(30, "EASY", "MATCH character_tesk"),
    ]
    decisions = [_d(0, "SKIP"), _d(20, "NEW", new_type="object")]
    m = _metrics(gold, decisions)
    assert m.by_category["SKIP"].correct == 2  # SKIP, and no decision
    assert m.by_category["EASY"].value == 0.0  # a linked gold needs a decision
    assert m.new_precision == 0.0


def test_c_at_10_counts_gold_id_among_candidates():
    gold = [
        _mention(0, "DESC", "MATCH character_nahle"),
        _mention(10, "EASY", "MATCH character_tesk"),
        _mention(20, "PART", "ALIAS location_cantine short"),
        _mention(30, "NEW", "NEW character"),  # not an existing gold: not counted
    ]
    far = [f"character_x{i}" for i in range(10)]
    candidates = {
        0: ["character_tesk", "character_nahle"],
        10: [*far, "character_tesk"],  # 11th: beyond the top 10
        30: ["character_tesk"],
    }  # 20 has no candidate list at all
    m = _metrics(gold, [], candidates=candidates)
    assert m.c_at_10 == pytest.approx(1 / 3)


def test_hard_pool_and_macro_differ_on_unbalanced_categories():
    gold = [_mention(i * 10, "DESC", "MATCH character_nahle") for i in range(9)]
    gold.append(_mention(100, "GAP", "MATCH character_tesk"))
    gold.append(_mention(110, "EASY", "MATCH character_tesk"))
    decisions = [_d(i * 10, "MATCH", "character_nahle") for i in range(9)]
    decisions.append(_d(100, "NEW", new_type="character"))
    decisions.append(_d(110, "MATCH", "character_tesk"))
    m = _metrics(gold, decisions)
    assert m.hard_pool.value == pytest.approx(9 / 10)
    assert m.hard_macro == pytest.approx((1.0 + 0.0) / 2)  # only categories present
    assert m.easy_pool.value == 1.0
    assert m.by_category_type[("DESC", "character")].value == 1.0


def test_usage_rates_and_cost():
    gold = [_mention(0, "EASY", "MATCH character_tesk"), _mention(10, "SKIP", "SKIP")]
    s1, s2 = _scene(gold, "a"), _scene(gold, "b")
    r1 = _run(s1, [_d(0, "MATCH", "character_tesk", deterministic=True)],
              usage={"calls": 1, "input_tokens": 100})  # fmt: skip
    r2 = _run(s2, [_d(0, "MATCH", "character_tesk", escalated=True), _d(10, "SKIP")],
              usage={"calls": 2, "input_tokens": 300})  # fmt: skip
    m = aggregate([score_scene(s1, r1), score_scene(s2, r2)])
    assert m.deterministic_share == pytest.approx(1 / 3)
    assert m.escalation_rate == pytest.approx(1 / 2)  # escalated turns / turns
    assert m.cost["calls"] == 3 and m.cost["per_turn_input_tokens"] == 200


def test_score_scene_rejects_a_result_of_another_scene():
    scene = _scene([])
    with pytest.raises(ValueError):
        score_scene(scene, RunResult("other", [], {}, {}))


def _hard_scene(i: int, correct: int, total: int = 4):
    gold = [_mention(k * 10, "DESC", "MATCH character_nahle") for k in range(total)]
    decisions = [
        _d(k * 10, "MATCH", "character_nahle" if k < correct else "character_tesk")
        for k in range(total)
    ]
    scene = _scene(gold, f"s{i}")
    return score_scene(scene, _run(scene, decisions))


def _hard_pool(scores) -> float:
    return aggregate(scores).hard_pool.value


def test_bootstrap_ci_contains_point_estimate_and_narrows_with_more_scenes():
    pattern = [4, 2, 3, 1, 4, 3, 0, 4]
    few = [_hard_scene(i, c) for i, c in enumerate(pattern)]
    many = [_hard_scene(i, c) for i, c in enumerate(pattern * 8)]
    point = _hard_pool(few)
    low, high = bootstrap.ci(few, _hard_pool, iterations=500, seed=1)
    assert low <= point <= high
    assert low < high
    low_many, high_many = bootstrap.ci(many, _hard_pool, iterations=500, seed=1)
    assert low_many <= _hard_pool(many) <= high_many
    assert high_many - low_many < high - low
    assert bootstrap.ci(few, _hard_pool, iterations=200, seed=3) == bootstrap.ci(
        few, _hard_pool, iterations=200, seed=3
    )


def test_bootstrap_ci_of_an_empty_metric_is_nan():
    scores = [score_scene(_scene([]), _run(_scene([]), []))]
    low, high = bootstrap.ci(scores, _hard_pool, iterations=50)
    assert math.isnan(low) and math.isnan(high)


def test_b_cubed_perfect_is_one_and_a_merge_lowers_precision():
    gold = {"a": {"1", "2"}, "b": {"3"}, "c": {"4", "5"}}
    assert coref.b_cubed(gold, gold) == pytest.approx((1.0, 1.0, 1.0))
    merged = {"x": {"1", "2", "3"}, "c": {"4", "5"}}
    p, r, f = coref.b_cubed(gold, merged)
    # mentions 1, 2: 2/3 each, 3: 1/3, 4, 5: 1 -> (2/3 + 2/3 + 1/3 + 1 + 1) / 5
    assert p == pytest.approx((2 / 3 + 2 / 3 + 1 / 3 + 2) / 5)
    assert r == 1.0
    assert f == pytest.approx(2 * p / (p + 1))
    split = {"a1": {"1"}, "a2": {"2"}, "b": {"3"}, "c": {"4", "5"}}
    p, r, _ = coref.b_cubed(gold, split)
    assert p == 1.0 and r == pytest.approx((0.5 + 0.5 + 1 + 1 + 1) / 5)


def test_ceaf_e_perfect_is_one():
    gold = {"a": {"1", "2"}, "b": {"3"}, "c": {"4", "5"}}
    assert coref.ceaf_e(gold, gold) == pytest.approx(1.0)
    renamed = {"z": {"4", "5"}, "y": {"1", "2"}, "x": {"3"}}
    assert coref.ceaf_e(gold, renamed) == pytest.approx(1.0)


def test_ceaf_e_uses_the_best_alignment():
    gold = {"a": {"1", "2", "3"}, "b": {"4"}}
    system = {"x": {"1", "2"}, "y": {"3", "4"}}
    # best: a-x (2*2/5 = 0.8) + b-y (2*1/3); P = R = sum / 2
    expected = (0.8 + 2 / 3) / 2
    assert coref.ceaf_e(gold, system) == pytest.approx(expected)
    assert coref.ceaf_e(gold, {}) == 0.0
