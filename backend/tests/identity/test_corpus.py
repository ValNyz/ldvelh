"""Identity gold corpus: format, loader and validation (#151)."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from evals.identity.corpus import (
    Scene,
    load_scenes,
    load_sequences,
    parse_expected,
    validate_scene,
    validate_sequence,
)

ROOT = Path(__file__).resolve().parent.parent / "fixtures" / "identity"
NARRATION = "La Kethari âgée cligne des yeux. — Nahle, dit-elle. Le terminal vibre sous sa paume."


def _scene(**overrides) -> dict:
    """A minimal valid scene; tests break one thing at a time."""
    data = {
        "id": "unit-scene",
        "genre": "sf",
        "source": "synthetic",
        "world": [
            {
                "id": "protagonist_valentin",
                "type": "protagonist",
                "label": "Valentin",
                "true_name": "Valentin",
                "known": True,
                "aliases": [{"text": "Valentin", "kind": "true_name", "known": True}],
            },
            {
                "id": "character_kethari_agee",
                "type": "character",
                "label": "La Kethari âgée",
                "descriptor": "La Kethari âgée",
                "known": False,
                "aliases": [
                    {"text": "La Kethari âgée", "kind": "descriptor", "known": True}
                ],
            },
        ],
        "history": [],
        "scene": {
            "location": "",
            "present": ["character_kethari_agee"],
            "reveals": [],
            "planned_npcs": [],
            "secrets": [],
            "open_disclosures": [],
        },
        "narration": NARRATION,
        "gold": [
            {
                "surface": "La Kethari âgée",
                "start": 0,
                "category": "DESC",
                "expected": "MATCH character_kethari_agee",
            },
            {
                "surface": "Nahle",
                "start": NARRATION.index("Nahle"),
                "category": "REVEAL",
                "expected": "ALIAS character_kethari_agee true_name",
            },
            {
                "surface": "sa paume",
                "start": NARRATION.index("sa paume"),
                "category": "SKIP",
                "expected": "SKIP",
            },
        ],
        "gold_effects": {
            "reveals": [{"ref": "character_kethari_agee", "real_name": "Nahle"}],
            "merges": [],
            "forbidden_merges": [],
        },
        "gold_knowledge": [],
    }
    data.update(overrides)
    return data


def _errors(**overrides) -> list[str]:
    return validate_scene(Scene.model_validate(_scene(**overrides)))


def _with_gold(index: int, **changes) -> list[dict]:
    gold = _scene()["gold"]
    gold[index] = {**gold[index], **changes}
    return gold


def test_minimal_scene_is_valid():
    assert _errors() == []


def test_example_scene_loads_and_validates():
    scenes = load_scenes(ROOT, include_examples=True)
    example = next(s for s in scenes if s.id == "example-f134-t15")
    assert validate_scene(example) == []
    categories = {m.category for m in example.gold}
    assert {"DESC", "REVEAL", "SKIP"} <= categories
    paume = [m for h in example.history for m in h.mentions if m.surface == "sa paume"]
    assert paume and all(m.expected == "SKIP" for m in paume)


def test_examples_are_left_out_of_the_corpus_by_default():
    assert all(not s.id.startswith("example-") for s in load_scenes(ROOT))


def test_validation_reports_surface_offset_mismatch():
    errors = _errors(gold=_with_gold(2, start=3))
    assert len(errors) == 1
    assert "sa paume" in errors[0] and "3" in errors[0]


def test_validation_reports_history_offset_mismatch():
    history = [
        {
            "text": "Le gérant attend.",
            "mentions": [
                {
                    "surface": "Le gérant",
                    "start": 1,
                    "category": "DESC",
                    "expected": "MATCH character_kethari_agee",
                }
            ],
        }
    ]
    errors = _errors(history=history)
    assert len(errors) == 1 and "Le gérant" in errors[0] and "history[0]" in errors[0]


def test_validation_rejects_unknown_expected_id():
    errors = _errors(gold=_with_gold(0, expected="MATCH character_nobody"))
    assert len(errors) == 1 and "character_nobody" in errors[0]


def test_validation_rejects_unknown_accept_also_id():
    errors = _errors(gold=_with_gold(0, accept_also=["MATCH character_ghost"]))
    assert len(errors) == 1 and "character_ghost" in errors[0]


def test_validation_rejects_a_hard_category_on_a_skip_gold():
    errors = _errors(gold=_with_gold(2, category="DESC"))
    assert len(errors) == 1 and "SKIP" in errors[0] and "DESC" in errors[0]


def test_validation_rejects_a_skip_category_on_a_linked_gold():
    errors = _errors(gold=_with_gold(0, category="SKIP"))
    assert len(errors) == 1 and "La Kethari âgée" in errors[0]


def test_validation_rejects_a_secret_absent_from_the_world():
    scene = _scene()
    scene["scene"]["secrets"] = ["character_spy"]
    errors = validate_scene(Scene.model_validate(scene))
    assert len(errors) == 1 and "character_spy" in errors[0]


def test_validation_rejects_a_reveal_without_gold_effect():
    errors = _errors(gold_effects={"reveals": [], "merges": [], "forbidden_merges": []})
    assert len(errors) == 1 and "REVEAL" in errors[0]


def test_validation_rejects_a_trap_outside_the_new_category():
    errors = _errors(gold=_with_gold(0, trap=True))
    assert len(errors) == 1 and "trap" in errors[0]


def test_validation_checks_knowledge_items_against_the_world():
    unknown_name = {
        "ref": "character_kethari_agee",
        "kind": "name",
        "state": "unknown",
        "text": "Nahle Irun-Sa",
    }
    errors = _errors(gold_knowledge=[unknown_name])
    assert len(errors) == 1 and "Nahle Irun-Sa" in errors[0]


def test_validation_checks_the_secret_state_of_a_name():
    scene = _scene()
    scene["world"][1]["true_name"] = "Nahle Irun-Sa"
    scene["world"][1]["aliases"].append(
        {"text": "Nahle Irun-Sa", "kind": "true_name", "known": False, "secret": True}
    )
    scene["gold_knowledge"] = [
        {
            "ref": "character_kethari_agee",
            "kind": "name",
            "state": "unknown",
            "text": "Nahle Irun-Sa",
        }
    ]
    errors = validate_scene(Scene.model_validate(scene))
    assert len(errors) == 1 and "secret" in errors[0]
    scene["gold_knowledge"][0]["state"] = "secret"
    assert validate_scene(Scene.model_validate(scene)) == []


def test_malformed_expected_is_rejected_at_load():
    with pytest.raises(ValidationError):
        Scene.model_validate(_scene(gold=_with_gold(0, expected="MATCH")))
    with pytest.raises(ValidationError):
        Scene.model_validate(
            _scene(gold=_with_gold(0, expected="ALIAS character_kethari_agee nom"))
        )
    with pytest.raises(ValidationError):
        Scene.model_validate(_scene(gold=_with_gold(0, expected="NEW protagonist")))


def test_unknown_field_is_rejected_at_load():
    with pytest.raises(ValidationError):
        Scene.model_validate(_scene(naration="typo"))


def test_parse_expected():
    assert parse_expected("MATCH character_x") == ("MATCH", "character_x", None, None)
    assert parse_expected("ALIAS character_x short") == (
        "ALIAS",
        "character_x",
        "short",
        None,
    )
    assert parse_expected("NEW location") == ("NEW", None, None, "location")
    assert parse_expected("SKIP") == ("SKIP", None, None, None)


def test_every_committed_scene_is_valid():
    scenes = load_scenes(ROOT, include_examples=True)
    assert scenes, "no scene found under fixtures/identity/scenes"
    errors = [f"{s.id}: {e}" for s in scenes for e in validate_scene(s)]
    errors += [
        f"{q.id}: {e}" for q in load_sequences(ROOT) for e in validate_sequence(q)
    ]
    ids = [s.id for s in scenes]
    duplicates = {i for i in ids if ids.count(i) > 1}
    assert not duplicates, f"duplicate scene ids: {sorted(duplicates)}"
    assert errors == []
