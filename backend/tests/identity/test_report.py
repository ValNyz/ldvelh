"""Identity evaluation report: gate table, floors, caveat (#151, spec § 3.5)."""

import math

from evals.identity import bootstrap, report
from evals.identity.corpus import Scene, Sequence
from evals.identity.scorer import Decision, RunResult, aggregate, score_scene

WORLD = [
    {"id": "protagonist_val", "type": "protagonist", "label": "Val", "known": True,
     "true_name": "Val"},
    {"id": "character_nahle", "type": "character", "label": "La Kethari âgée",
     "known": False},
    {"id": "location_cantine", "type": "location", "label": "Cantine", "known": True},
]  # fmt: skip
CAVEAT = "chiffres = accord avec l'annotateur unique, plafond humain non mesuré"


def _scene(scene_id: str, gold: list[tuple[int, str, str]]) -> Scene:
    return Scene.model_validate(
        {
            "id": scene_id,
            "genre": "sf",
            "campaign": "unit",
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
            "narration": "x" * 100,
            "gold": [
                {
                    "surface": f"m{start}",
                    "start": start,
                    "category": category,
                    "expected": expected,
                }
                for start, category, expected in gold
            ],
            "gold_effects": {"reveals": [], "merges": [], "forbidden_merges": []},
            "gold_knowledge": [],
        }
    )


def _d(start, decision, entity_id=None, kind=None, new_type=None, **flags):
    return Decision(f"m{start}", start, decision, entity_id, kind, new_type, **flags)


SCENE_A = _scene(
    "a",
    [(0, "DESC", "MATCH character_nahle"), (10, "NEW", "NEW character"),
     (20, "EASY", "MATCH location_cantine"), (30, "SKIP", "SKIP")],
)  # fmt: skip
SCENE_B = _scene(
    "b", [(0, "PART", "MATCH character_nahle"), (10, "PC", "MATCH protagonist_val")]
)


def _run(wrong_part: bool) -> list:
    a = RunResult(
        "a",
        [_d(0, "MATCH", "character_nahle", deterministic=True),
         _d(10, "NEW", new_type="character"),
         _d(20, "MATCH", "location_cantine", deterministic=True),
         _d(40, "NEW", new_type="object")],  # spurious NEW
        {0: ["character_nahle"], 20: ["location_cantine"]},
        {"input_tokens": 1000, "calls": 1},
    )  # fmt: skip
    part = "location_cantine" if wrong_part else "character_nahle"
    b = RunResult(
        "b",
        [_d(0, "MATCH", part, escalated=True), _d(10, "MATCH", "protagonist_val")],
        {0: ["character_nahle"], 10: ["protagonist_val"]},
        {"input_tokens": 3000, "calls": 2},
    )
    return [score_scene(SCENE_A, a), score_scene(SCENE_B, b)]


RUNS = [_run(False), _run(True), _run(False)]


def _render(**kwargs):
    defaults = {
        "provider": "anthropic",
        "models": {"identity": "claude-haiku-4-5"},
        "split": "test",
        "header_note": "subagent run, not the API path",
        "iterations": 200,
    }
    return report.render(RUNS, **{**defaults, **kwargs})


def _row(data: dict, name: str) -> dict:
    return next(r for r in data["gate"] if r["name"] == name)


def test_report_prints_the_single_annotator_caveat_and_both_floor_readings():
    markdown, data = _render()
    head = markdown.split("\n## ", 1)[0]
    assert CAVEAT in head and "D25" in head
    assert "subagent run, not the API path" in head
    assert "0,85" in markdown and "0,88" in markdown
    assert "60 mentions" in markdown
    floors = data["floors"]
    assert floors["indicative"]["threshold"] == 0.85
    assert floors["binding"]["threshold"] == 0.88
    assert floors["binding"]["applies"] is False  # 1 mention per category, not 60
    assert floors["indicative"]["verdicts"]["DESC"] == "OK"
    assert data["caveat"] == CAVEAT


def test_report_gate_rows_use_the_pooled_estimator_and_pooled_scene_bootstrap():
    _, data = _render()
    pool = _row(data, "hard_pool")
    pooled = [s for run in RUNS for s in run]
    assert pool["per_run"] == [1.0, 2 / 3, 1.0]
    assert pool["estimator"] == "pooled"
    assert pool["value"] == aggregate(pooled).hard_pool.value
    assert math.isclose(pool["value"], (1 + 2 / 3 + 1) / 3)
    assert pool["threshold"] == 0.90 and pool["verdict"] == "ÉCHEC"
    expected = bootstrap.ci(
        pooled, lambda s: aggregate(s).hard_pool.value, iterations=200
    )
    assert pool["ci"] == list(expected)
    assert _row(data, "easy_pool")["verdict"] == "OK"
    assert _row(data, "c_at_10")["value"] == 1.0
    assert data["gate_passed"] is False
    assert pool["undefined_draws"] == 0


def test_report_names_missing_hard_categories_and_never_passes_the_macro():
    markdown, data = _render()
    assert data["missing_hard_categories"] == ["GAP", "REVEAL", "XTYPE"]
    macro = _row(data, "hard_macro")
    assert macro["value"] is None and macro["verdict"] == "ÉCHEC"
    assert "GAP, REVEAL, XTYPE" in markdown


def test_report_prints_rates_type_table_cost_and_unmeasured_rows():
    markdown, data = _render()
    rates = data["rates"]
    assert rates["spurious_new_per_turn"] == 0.5
    assert rates["new_type_errors"] == 0
    assert math.isclose(rates["deterministic_share"], 2 / 5)
    assert data["cost"]["per_turn_input_tokens"] == 2000
    assert data["category_type"]["PART"]["character"]["accuracy"] == 2 / 3
    assert "étage bon marché seul : non exécuté" in markdown
    assert {r["name"] for r in data["not_measured"]} == {"R", "P", "L"}
    for label in ("Fusions parasites", "Erreurs de type NEW", "Part déterministe",
                  "Coût par tour", "Catégorie × type"):  # fmt: skip
        assert label in markdown


def test_report_prints_the_cheap_tier_line_and_coref_lines():
    turn = _scene("q-t1", [(0, "DESC", "MATCH character_nahle"),
                           (10, "PART", "MATCH character_nahle")])  # fmt: skip
    sequence = Sequence(id="q", turns=[turn], gold_clusters={
        "character_nahle": ["q-t1:0", "q-t1:10"]})  # fmt: skip
    result = RunResult(
        "q-t1",
        [_d(0, "MATCH", "character_nahle"), _d(10, "MATCH", "character_nahle")],
        {},
        {},
    )
    markdown, data = _render(
        cheap_scores_by_run=[_run(True)],
        sequence_results_by_run=[[(sequence, [result])]] * 3,
    )
    assert data["cheap_tier"]["hard_pool"] == 2 / 3
    assert "étage bon marché seul" in markdown
    assert data["coref"]["b_cubed"]["mean"] == 1.0
    assert data["coref"]["ceaf_e"]["mean"] == 1.0
    assert "B³" in markdown and "CEAF-e" in markdown


def test_report_never_reads_as_a_complete_pass_while_r_p_l_are_unmeasured():
    markdown, data = _render()
    assert data["gate_complete"] is False
    assert "incomplète (R, P, L non mesurés)" in markdown


def test_report_takes_c_at_10_from_the_dev_and_test_blocking_run_when_given():
    miss = RunResult("b", [], {0: ["location_cantine"], 10: ["protagonist_val"]}, {})
    scores = [_run(False)[0], score_scene(SCENE_B, miss)]
    markdown, data = _render(c_at_10_scores=scores)
    row = _row(data, "c_at_10")
    assert row["value"] == 3 / 4 and row["per_run"] == [3 / 4]
    assert row["verdict"] == "ÉCHEC"
    assert data["c_at_10_source"] == "dev + test, 1 run"
    _, default = _render()
    assert default["c_at_10_source"] == "runs of this report"
    assert "dev + test" in markdown


def test_report_counts_the_bootstrap_draws_where_a_row_is_undefined():
    markdown, data = _render()
    assert _row(data, "hard_macro")["undefined_draws"] == 200
    # PART is only in scene b: a draw without b leaves it undefined
    part = _row(data, "A_PART")["undefined_draws"]
    assert 0 < part < 200
    assert "tirages" in markdown


# --- final review M2 and M6 ---


def test_the_floors_table_names_the_split_it_counts():
    markdown, _ = _render(split="dev")
    assert "| Mentions dev |" in markdown and "Mentions test" not in markdown


def test_imported_answers_print_an_unmeasured_cost():
    markdown, data = _render(cost_measured=False)
    assert "Coût par tour : non mesuré (réponses importées)" in markdown
    assert data["cost_measured"] is False
    assert "non mesuré (réponses importées)" not in _render()[0]
