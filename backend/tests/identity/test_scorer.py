"""Identity scorer, per-scene bootstrap and coreference metrics (#151)."""

import itertools
import math
import random

import pytest

from evals.identity import bootstrap, coref
from evals.identity.corpus import Scene, Sequence
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


def _mention(start, category, expected, surface=None, **extra) -> dict:
    return {"surface": surface or f"m{start}", "start": start, "category": category,
            "expected": expected, **extra}  # fmt: skip


def _scene(gold: list[dict], scene_id: str = "s1") -> Scene:
    return Scene.model_validate(_scene_data(gold, scene_id))


def _scene_data(gold: list[dict], scene_id: str) -> dict:
    return {
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


def _d(
    start, decision, entity_id=None, kind=None, new_type=None, surface=None, **flags
) -> Decision:
    surface = surface or f"m{start}"
    return Decision(surface, start, decision, entity_id, kind, new_type, **flags)


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
    assert m.hard_macro_present == pytest.approx((1.0 + 0.0) / 2)
    assert math.isnan(m.hard_macro)  # PART, REVEAL, NEW, XTYPE are missing
    assert m.hard_categories_missing == ("PART", "REVEAL", "NEW", "XTYPE")
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


# --- fix round 1 -------------------------------------------------------------


def test_new_needs_the_right_type():
    gold = [_mention(0, "NEW", "NEW character"), _mention(10, "NEW", "NEW location")]
    decisions = [
        _d(0, "NEW", new_type="location"),
        _d(10, "NEW", new_type="location"),
    ]
    m = _metrics(gold, decisions)
    assert m.by_category["NEW"].correct == 1
    assert m.new_type_errors == 1
    assert m.new_recall == 1.0 and m.new_precision == 1.0  # NIL detection only


def test_hard_macro_needs_every_hard_category():
    categories = ["PART", "DESC", "GAP", "REVEAL", "NEW", "XTYPE"]
    gold, decisions = [], []
    for i, category in enumerate(categories):
        if category == "NEW":
            gold.append(_mention(i * 10, category, "NEW character"))
            decisions.append(_d(i * 10, "NEW", new_type="character"))
        else:
            gold.append(_mention(i * 10, category, "MATCH character_tesk"))
            ok = category != "GAP"
            decisions.append(_d(i * 10, "MATCH", "character_tesk" if ok else "x"))
    m = _metrics(gold, decisions)
    assert m.hard_categories_missing == ()
    assert m.hard_macro == pytest.approx(5 / 6) == m.hard_macro_present


def test_duplicate_decisions_at_one_start_are_rejected():
    scene = _scene([_mention(0, "EASY", "MATCH character_tesk")])
    decisions = [_d(0, "MATCH", "character_tesk"), _d(0, "NEW", new_type="object")]
    with pytest.raises(ValueError, match="start 0"):
        score_scene(scene, _run(scene, decisions))


KETHARI = "La Kethari âgée"


def test_a_surface_without_its_determiner_aligns_by_its_end():
    gold = [_mention(0, "DESC", "MATCH character_nahle", surface=KETHARI)]
    decision = _d(3, "MATCH", "character_nahle", surface="Kethari âgée")
    m = _metrics(gold, [decision], candidates={3: ["character_nahle"]})
    assert m.by_category["DESC"].value == 1.0
    assert m.c_at_10 == 1.0  # candidates keyed by the system start are found
    assert m.spurious_link_per_turn == 0.0


TERMINAL = "le terminal du Kethari au tablier"
NESTED = TERMINAL.index("Kethari")


def _nested_gold() -> list[dict]:
    return [
        _mention(0, "SKIP", "SKIP", surface=TERMINAL),
        _mention(NESTED, "DESC", "MATCH character_tesk", surface="Kethari au tablier"),
    ]


def test_a_shared_end_falls_back_to_the_innermost_containing_mention():
    start = TERMINAL.index("au tablier")
    decision = _d(start, "MATCH", "character_tesk", surface="au tablier")
    m = _metrics(_nested_gold(), [decision])
    assert m.by_category["DESC"].value == 1.0  # not the enclosing SKIP
    assert m.by_category["SKIP"].value == 1.0


def test_a_span_inside_a_skip_aligns_to_the_skip():
    decision = _d(3, "MATCH", "object_terminal", surface="terminal")
    m = _metrics(_nested_gold(), [decision])
    assert m.by_category["SKIP"].value == 0.0
    assert m.W == pytest.approx(1 / 2)


def test_unaligned_decisions_are_counted_as_spurious():
    gold = [_mention(0, "EASY", "MATCH character_tesk")]
    decisions = [
        _d(0, "MATCH", "character_tesk"),
        _d(50, "NEW", new_type="object"),  # junk entity on unannotated scenery
        _d(80, "MATCH", "character_nahle"),  # a link on an unannotated span
        _d(120, "SKIP"),  # not linked, not created: ignored
        _d(150, "UNSURE"),
    ]
    m = _metrics(gold, decisions)
    assert m.spurious_new_per_turn == 1.0
    assert m.spurious_link_per_turn == 1.0
    assert m.new_precision == 0.0  # the spurious NEW is a false NEW
    assert m.W == 0.0  # it overlaps no gold mention: not a wrong merge
    assert m.D == 0.0
    assert m.by_category["EASY"].value == 1.0


def test_a_pronoun_linked_outside_the_gold_is_not_a_wrong_merge():
    gold = [_mention(0, "DESC", "MATCH character_nahle", surface=KETHARI)]
    decisions = [
        _d(0, "MATCH", "character_nahle", surface=KETHARI),
        _d(40, "MATCH", "character_nahle", surface="elle"),  # unannotated pronoun
    ]
    m = _metrics(gold, decisions)
    assert m.W == 0.0
    assert m.spurious_link_per_turn == 1.0


NAHLE = "Nahle Irun-Sa"
IRUN = NAHLE.index("Irun-Sa")


def _split_name(second: Decision):
    gold = [_mention(0, "DESC", "MATCH character_nahle", surface=NAHLE)]
    first = _d(0, "MATCH", "character_nahle", surface="Nahle")
    return _metrics(gold, [first, second])


def test_a_split_name_on_the_same_entity_is_not_a_wrong_merge():
    m = _split_name(_d(IRUN, "MATCH", "character_nahle", surface="Irun-Sa"))
    assert m.W == 0.0
    assert m.spurious_link_per_turn == 1.0
    assert m.by_category["DESC"].value == 1.0


def test_an_overlapping_spurious_link_to_another_id_is_a_wrong_merge():
    m = _split_name(_d(IRUN, "MATCH", "character_tesk", surface="Irun-Sa"))
    assert m.W == 1.0


def test_a_nested_gold_that_accepts_the_id_absolves_a_spurious_link():
    start = TERMINAL.index("tablier")
    decisions = [
        _d(NESTED, "MATCH", "character_tesk", surface="Kethari au tablier"),
        _d(start, "MATCH", "character_tesk", surface="tablier"),  # spurious
    ]
    m = _metrics(_nested_gold(), decisions)
    assert m.spurious_link_per_turn == 1.0
    assert m.W == 0.0  # inside the enclosing SKIP, but on its own entity's mention


def test_a_spurious_new_on_an_existing_gold_is_a_duplicate():
    m = _split_name(_d(IRUN, "NEW", new_type="character", surface="Irun-Sa"))
    assert m.D == 1.0
    assert m.new_precision == 0.0
    assert m.spurious_new_per_turn == 1.0


def test_an_empty_surface_does_not_align_by_its_end():
    gold = [_mention(0, "EASY", "MATCH character_tesk", surface="Tesk")]
    empty = Decision("", 4, "MATCH", "character_tesk", None, None)
    m = _metrics(gold, [empty])
    assert m.by_category["EASY"].value == 0.0
    assert m.spurious_link_per_turn == 1.0
    assert m.W == 0.0  # an empty span overlaps nothing


def _bootstrap_pattern():
    return [_hard_scene(i, c) for i, c in enumerate([4, 2, 3, 1, 4, 3, 0, 4])]


def test_bootstrap_resamples_whole_scenes_across_runs():
    single = _bootstrap_pattern()
    pooled = single * 3  # 3 runs of the same 8 scenes
    one_run = bootstrap.ci(single, _hard_pool, iterations=500, seed=2)
    assert bootstrap.ci(pooled, _hard_pool, iterations=500, seed=2) == one_run
    unique = iter(range(len(pooled)))
    low, high = bootstrap.ci(
        pooled, _hard_pool, iterations=500, seed=2, key=lambda s: next(unique)
    )
    assert high - low < one_run[1] - one_run[0]  # independent draws: too narrow


def _seq_turn(scene_id: str, gold: list[dict]) -> dict:
    return _scene_data(gold, scene_id)


def test_system_clusters_follow_the_ids_the_system_gave():
    sequence = Sequence.model_validate(
        {
            "id": "seq",
            "turns": [
                _seq_turn("t1", [
                    _mention(0, "EASY", "MATCH character_tesk"),
                    _mention(10, "NEW", "NEW character"),
                    _mention(20, "SKIP", "SKIP"),
                ]),
                _seq_turn("t2", [
                    _mention(0, "DESC", "MATCH character_tesk"),
                    _mention(30, "DESC", "MATCH character_tesk"),
                ]),
            ],
            "gold_clusters": {
                "character_tesk": ["t1:0", "t2:0", "t2:30"],
                "character_new": ["t1:10"],
            },
        }
    )  # fmt: skip
    results = [
        RunResult("t1", [
            _d(0, "MATCH", "character_tesk"),
            _d(10, "NEW", "sys_1", new_type="character"),
            _d(20, "SKIP"),
        ], {}, {}),
        RunResult("t2", [
            _d(0, "MATCH", "sys_1"),
            _d(30, "MATCH", "character_tesk"),
            _d(60, "NEW", new_type="object"),  # spurious, no system id
        ], {}, {}),
    ]  # fmt: skip
    system = coref.system_clusters(sequence, results)
    assert sorted(map(sorted, system.values())) == [
        ["t1:0", "t2:30"],
        ["t1:10", "t2:0"],
        ["t2:60"],
    ]
    gold = coref.gold_clusters(sequence)
    assert gold == {"character_tesk": {"t1:0", "t2:0", "t2:30"},
                    "character_new": {"t1:10"}}  # fmt: skip
    p, r, _ = coref.b_cubed(gold, system)
    assert p < 1.0 and r < 1.0


def test_b_cubed_accepts_any_cluster_id_and_rejects_double_membership():
    gold = {"": {"1", "2"}, "b": {"3"}}
    assert coref.b_cubed(gold, {"x": {"1", "2"}, "y": {"3"}}) == (1.0, 1.0, 1.0)
    assert coref.b_cubed({"a": {"1"}}, {"": {"2"}})[0] == 0.0
    with pytest.raises(ValueError, match="'1'"):
        coref.b_cubed({"a": {"1"}, "b": {"1", "2"}}, gold)


def test_ceaf_e_ignores_empty_clusters():
    gold = {"a": {"1", "2"}, "b": {"3"}}
    assert coref.ceaf_e(gold, {**gold, "empty": set()}) == pytest.approx(1.0)


def test_kuhn_munkres_beats_a_greedy_matching():
    pairs = coref.max_weight_assignment([[0.9, 0.8], [0.8, 0.0]])
    assert sorted(pairs) == [(0, 1), (1, 0)]  # 1.6; greedy takes 0.9 then 0.0


def test_kuhn_munkres_matches_brute_force():
    rng = random.Random(7)
    for _ in range(300):
        rows, cols = rng.randint(1, 5), rng.randint(1, 5)
        weights = [[rng.choice([0, 0.25, 0.5, 2 / 3, 1]) for _ in range(cols)]
                   for _ in range(rows)]  # fmt: skip
        if rows <= cols:
            best = max(sum(weights[i][p[i]] for i in range(rows))
                       for p in itertools.permutations(range(cols), rows))  # fmt: skip
        else:
            best = max(sum(weights[p[j]][j] for j in range(cols))
                       for p in itertools.permutations(range(rows), cols))  # fmt: skip
        pairs = coref.max_weight_assignment(weights)
        assert sum(weights[i][j] for i, j in pairs) == pytest.approx(best)
        assert len({i for i, _ in pairs}) == len({j for _, j in pairs}) == len(pairs)
