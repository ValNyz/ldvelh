"""Identity gold corpus: format, loader and validation (#151)."""

import random
import re
from collections import Counter
from pathlib import Path

import pytest
from pydantic import ValidationError

from evals.identity import corpus
from evals.identity.corpus import (
    HARD_CATEGORIES,
    Expected,
    Scene,
    Sequence,
    load_scenes,
    load_sequences,
    load_split,
    parse_expected,
    validate_scene,
    validate_sequence,
)
from evals.identity.split import shares_in_test, stratified_split
from evals.identity.carried import carried_objects
from scripts import identity_corpus_carried

ROOT = Path(__file__).resolve().parent.parent / "fixtures" / "identity"
NARRATION = "La Kethari âgée cligne des yeux. — Nahle, dit-elle. Le terminal vibre sous sa paume."


def _scene(**overrides) -> dict:
    """A minimal valid scene; tests break one thing at a time."""
    data = {
        "id": "unit-scene",
        "genre": "sf",
        "campaign": "unit",
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
    assert parse_expected("MATCH character_x") == Expected("MATCH", "character_x")
    assert parse_expected("ALIAS character_x short") == Expected(
        "ALIAS", "character_x", alias_kind="short"
    )
    assert parse_expected("NEW location") == Expected("NEW", new_type="location")
    assert parse_expected("SKIP") == Expected("SKIP")
    assert parse_expected("SAME 12") == Expected("SAME", same_start=12)
    for malformed in ("SAME", "SAME x", "SAME -1", "SAME 1 2"):
        with pytest.raises(ValueError):
            parse_expected(malformed)


def test_every_committed_scene_is_valid():
    scenes = load_scenes(ROOT, include_examples=True)
    sequences = load_sequences(ROOT)
    assert scenes, "no scene found under fixtures/identity/scenes"
    errors = [f"{s.id}: {e}" for s in scenes for e in validate_scene(s)]
    errors += [f"{q.id}: {e}" for q in sequences for e in validate_sequence(q)]
    ids = [s.id for s in scenes] + [t.id for q in sequences for t in q.turns]
    duplicates = {i for i in ids if ids.count(i) > 1}
    assert not duplicates, (
        f"duplicate scene ids across the corpus: {sorted(duplicates)}"
    )
    assert errors == []


# --- fix round 1: mechanical category rules, knowledge completeness, typed effects ---


def _entity(id_, type_, label, *, last_seen_turn=None, aliases=None, **extra):
    return {
        "id": id_,
        "type": type_,
        "label": label,
        "known": True,
        "last_seen_turn": last_seen_turn,
        "aliases": aliases
        if aliases is not None
        else [{"text": label, "kind": "label", "known": True}],
        **extra,
    }


def _custom(
    narration, gold, *, world_extra=(), history=(), turn=None, **overrides
) -> dict:
    """A valid base scene with another narration and gold (spans located by surface)."""
    data = _scene(
        narration=narration,
        gold=[
            {**g, "start": g.get("start", narration.index(g["surface"]))} for g in gold
        ],
        gold_effects={"reveals": [], "merges": [], "forbidden_merges": []},
        history=list(history),
        turn=turn,
    )
    data["world"] += list(world_extra)
    data.update(overrides)
    return data


def _custom_errors(*args, **kwargs) -> list[str]:
    return validate_scene(Scene.model_validate(_custom(*args, **kwargs)))


VOSS = _entity(
    "character_elara_voss",
    "character",
    "Elara Voss",
    last_seen_turn=3,
    aliases=[
        {"text": "Elara Voss", "kind": "true_name", "known": True},
        {"text": "Voss", "kind": "short", "known": True},
    ],
    true_name="Elara Voss",
)
BUREAU_LOC = _entity(
    "location_bureau_des_residences", "location", "Bureau des Résidences"
)
BUREAU_ORG = _entity(
    "organization_bureau_des_residences", "organization", "Bureau des Résidences"
)


def test_missing_category_is_rejected_at_load():
    gold = _scene()["gold"]
    del gold[0]["category"]
    with pytest.raises(ValidationError):
        Scene.model_validate(_scene(gold=gold))


def test_validation_rejects_a_new_decision_outside_the_new_category():
    errors = _errors(gold=_with_gold(0, expected="NEW character"))
    assert len(errors) == 1 and "NEW" in errors[0] and "DESC" in errors[0]


def test_validation_requires_pc_on_the_protagonist():
    errors = _errors(gold=_with_gold(0, expected="MATCH protagonist_valentin"))
    assert len(errors) == 1 and "PC" in errors[0]


def test_validation_rejects_pc_on_a_character():
    errors = _errors(gold=_with_gold(0, category="PC"))
    assert len(errors) == 1 and "PC" in errors[0]


def test_validation_requires_the_true_name_kind_on_a_reveal():
    errors = _errors(gold=_with_gold(1, expected="ALIAS character_kethari_agee short"))
    assert len(errors) == 1 and "true_name" in errors[0]


def test_validation_rejects_a_reveal_of_a_name_already_known():
    scene = _scene()
    scene["world"][1]["known"] = True
    scene["world"][1]["true_name"] = "Nahle"
    scene["world"][1]["aliases"].append(
        {"text": "Nahle", "kind": "true_name", "known": True}
    )
    errors = validate_scene(Scene.model_validate(scene))
    assert len(errors) == 1 and "already known" in errors[0]


def test_gap_needs_the_scene_turn():
    errors = _custom_errors(
        "Voss t'attend.",
        [
            {
                "surface": "Voss",
                "category": "GAP",
                "expected": "MATCH character_elara_voss",
            }
        ],
        world_extra=[VOSS],
    )
    assert len(errors) == 1 and "turn" in errors[0]


def test_gap_needs_an_old_last_seen_turn():
    errors = _custom_errors(
        "Voss t'attend.",
        [
            {
                "surface": "Voss",
                "category": "GAP",
                "expected": "MATCH character_elara_voss",
            }
        ],
        world_extra=[VOSS],
        turn=6,
    )
    assert len(errors) == 1 and "last_seen_turn" in errors[0]


def test_gap_needs_absence_from_the_history():
    history = [
        {
            "text": "Voss passe.",
            "mentions": [
                {
                    "surface": "Voss",
                    "start": 0,
                    "category": "PART",
                    "expected": "MATCH character_elara_voss",
                }
            ],
        }
    ]
    errors = _custom_errors(
        "Voss t'attend.",
        [
            {
                "surface": "Voss",
                "category": "GAP",
                "expected": "MATCH character_elara_voss",
            }
        ],
        world_extra=[VOSS],
        turn=21,
        history=history,
    )
    assert len(errors) == 1 and "history" in errors[0]


def test_validation_forces_gap_when_its_conditions_hold():
    errors = _custom_errors(
        "Voss t'attend.",
        [
            {
                "surface": "Voss",
                "category": "PART",
                "expected": "MATCH character_elara_voss",
            }
        ],
        world_extra=[VOSS],
        turn=21,
    )
    assert len(errors) == 1 and "GAP" in errors[0]


def test_valid_gap_passes():
    assert (
        _custom_errors(
            "Voss t'attend.",
            [
                {
                    "surface": "Voss",
                    "category": "GAP",
                    "expected": "MATCH character_elara_voss",
                }
            ],
            world_extra=[VOSS],
            turn=21,
        )
        == []
    )


def test_validation_forces_xtype_on_a_shared_name():
    errors = _custom_errors(
        "Tu entres au Bureau des Résidences.",
        [
            {
                "surface": "Bureau des Résidences",
                "category": "EASY",
                "expected": "MATCH location_bureau_des_residences",
            }
        ],
        world_extra=[BUREAU_LOC, BUREAU_ORG],
    )
    assert len(errors) == 1 and "XTYPE" in errors[0]


def test_validation_rejects_xtype_on_a_unique_name():
    errors = _custom_errors(
        "Tu entres au Bureau des Résidences.",
        [
            {
                "surface": "Bureau des Résidences",
                "category": "XTYPE",
                "expected": "MATCH location_bureau_des_residences",
            }
        ],
        world_extra=[BUREAU_LOC],
    )
    assert len(errors) == 1 and "XTYPE" in errors[0]


def test_easy_requires_the_exact_name_or_label():
    errors = _custom_errors(
        "Tu entres au Bureau.",
        [
            {
                "surface": "Bureau",
                "category": "EASY",
                "expected": "MATCH location_bureau_des_residences",
            }
        ],
        world_extra=[BUREAU_LOC],
    )
    assert len(errors) == 1 and "EASY" in errors[0]


def test_easy_accepts_the_label_with_a_determiner():
    assert (
        _custom_errors(
            "Tu vois le Bureau des Résidences.",
            [
                {
                    "surface": "le Bureau des Résidences",
                    "category": "EASY",
                    "expected": "MATCH location_bureau_des_residences",
                }
            ],
            world_extra=[BUREAU_LOC],
        )
        == []
    )


def test_history_mentions_cannot_be_gap():
    history = [
        {
            "text": "Le gérant attend.",
            "mentions": [
                {
                    "surface": "Le gérant",
                    "start": 0,
                    "category": "GAP",
                    "expected": "MATCH character_kethari_agee",
                }
            ],
        }
    ]
    errors = _errors(history=history)
    assert (
        errors
        and all("history" in e for e in errors)
        and any("GAP" in e for e in errors)
    )


def _tesk(**changes):
    return _entity(
        "character_tesk",
        "character",
        "Tesk Vahrun-Oo",
        true_name="Tesk Vahrun-Oo",
        descriptor="Le Kethari au tablier",
        known=False,
        aliases=[
            {"text": "Tesk Vahrun-Oo", "kind": "true_name", "known": False},
            {"text": "Le Kethari au tablier", "kind": "descriptor", "known": True},
        ],
        **changes,
    )


TESK_NAME = {
    "ref": "character_tesk",
    "kind": "name",
    "state": "unknown",
    "text": "Tesk Vahrun-Oo",
}


def test_validation_requires_a_knowledge_item_per_unknown_name():
    scene = _scene()
    scene["world"].append(_tesk())
    errors = validate_scene(Scene.model_validate(scene))
    assert (
        len(errors) == 1
        and "Tesk Vahrun-Oo" in errors[0]
        and "gold_knowledge" in errors[0]
    )
    scene["gold_knowledge"] = [TESK_NAME]
    assert validate_scene(Scene.model_validate(scene)) == []


def test_validation_rejects_a_duplicate_knowledge_item():
    scene = _scene(gold_knowledge=[TESK_NAME, TESK_NAME])
    scene["world"].append(_tesk())
    errors = validate_scene(Scene.model_validate(scene))
    assert len(errors) == 1 and "more than once" in errors[0]


def test_pov_error_is_only_for_the_reveal_of_a_real_scene():
    assert len(_errors(gold=_with_gold(1, pov_error=True))) == 1  # synthetic scene
    assert _errors(gold=_with_gold(1, pov_error=True), source="real") == []
    errors = _errors(gold=_with_gold(0, pov_error=True), source="real")
    assert len(errors) == 1 and "pov_error" in errors[0]


def test_unknown_key_in_effects_is_rejected_at_load():
    effects = {
        "reveals": [{"ref": "character_kethari_agee", "realname": "Nahle"}],
        "merges": [],
        "forbidden_merges": [],
    }
    with pytest.raises(ValidationError):
        Scene.model_validate(_scene(gold_effects=effects))
    with pytest.raises(ValidationError):
        Scene.model_validate(
            _scene(scene={**_scene()["scene"], "open_disclosures": [{"id": "x"}]})
        )


def test_negative_start_is_rejected_at_load():
    with pytest.raises(ValidationError):
        Scene.model_validate(_scene(gold=_with_gold(2, start=-9)))


def test_validation_rejects_two_mentions_with_the_same_start():
    gold = _scene()["gold"] + [_scene()["gold"][2]]
    errors = _errors(gold=gold)
    assert len(errors) == 1 and "same start" in errors[0]


def test_new_arc_is_rejected_at_load():
    with pytest.raises(ValidationError):
        Scene.model_validate(
            _scene(gold=_with_gold(0, category="NEW", expected="NEW arc"))
        )


def _sequence(**overrides) -> Sequence:
    turn = _scene(id="seq-t1")
    data = {
        "id": "seq",
        "turns": [turn],
        "gold_clusters": {
            "character_kethari_agee": ["seq-t1:0", f"seq-t1:{NARRATION.index('Nahle')}"]
        },
    }
    data.update(overrides)
    return Sequence.model_validate(data)


def test_valid_sequence_passes():
    assert validate_sequence(_sequence()) == []


def test_sequence_cluster_key_must_be_the_gold_entity():
    seq = _sequence(
        gold_clusters={
            "character_WRONG": ["seq-t1:0", f"seq-t1:{NARRATION.index('Nahle')}"]
        }
    )
    errors = validate_sequence(seq)
    assert len(errors) == 2 and all("character_WRONG" in e for e in errors)


def test_sequence_rejects_duplicate_turn_ids():
    seq = _sequence(turns=[_scene(id="seq-t1"), _scene(id="seq-t1")])
    assert any("duplicate turn id" in e for e in validate_sequence(seq))


# --- fix round 2: overlap sweep, reveal versus GAP, nameless entities, pronouns ---


def test_validation_finds_an_overlap_hidden_by_a_nested_span():
    gold = [
        {
            "surface": "La Kethari âgée",
            "category": "DESC",
            "expected": "MATCH character_kethari_agee",
        },
        {
            "surface": "Kethari",
            "category": "DESC",
            "expected": "MATCH character_kethari_agee",
        },
        {"surface": "âgée cligne", "category": "SKIP", "expected": "SKIP"},
    ]
    errors = _custom_errors(NARRATION, gold)
    assert len(errors) == 1 and "overlap" in errors[0]


def test_validation_rejects_a_skip_inside_a_skip():
    gold = _scene()["gold"] + [
        {
            "surface": "paume",
            "start": NARRATION.index("paume"),
            "category": "SKIP",
            "expected": "SKIP",
        }
    ]
    errors = _errors(gold=gold)
    assert len(errors) == 1 and "SKIP inside a SKIP" in errors[0]


TESK_OLD = _entity(
    "character_tesk",
    "character",
    "Tesk Vahrun-Oo",
    true_name="Tesk Vahrun-Oo",
    known=False,
    last_seen_turn=3,
    aliases=[
        {"text": "Tesk Vahrun-Oo", "kind": "true_name", "known": False},
        {"text": "Tesk", "kind": "short", "known": False},
    ],
)
TESK_REVEAL = "— Tesk Vahrun-Oo, dit-il. Tesk suffit."


def _tesk_reveal(short_category: str) -> list[str]:
    gold = [
        {
            "surface": "Tesk Vahrun-Oo",
            "category": "REVEAL",
            "expected": "ALIAS character_tesk true_name",
        },
        {
            "surface": "Tesk",
            "start": TESK_REVEAL.index("Tesk suffit"),
            "category": short_category,
            "expected": "ALIAS character_tesk short",
            "accept_also": ["MATCH character_tesk"],
        },
    ]
    return _custom_errors(
        TESK_REVEAL,
        gold,
        world_extra=[TESK_OLD],
        turn=21,
        gold_effects={
            "reveals": [{"ref": "character_tesk", "real_name": "Tesk Vahrun-Oo"}],
            "merges": [],
            "forbidden_merges": [],
        },
        gold_knowledge=[TESK_NAME],
    )


def test_a_short_form_after_a_reveal_is_part_even_when_gap_conditions_hold():
    assert _tesk_reveal("PART") == []


def test_gap_is_not_allowed_after_a_reveal_in_the_same_turn():
    errors = _tesk_reveal("GAP")
    assert len(errors) == 1 and "REVEAL" in errors[0]


ROOM = _entity(
    "location_salle_au_bout_du_couloir",
    "location",
    "la salle au bout du couloir",
    descriptor="la salle au bout du couloir",
    known=False,
    aliases=[
        {"text": "la salle au bout du couloir", "kind": "descriptor", "known": True}
    ],
)
BADGE = "Le badge dit : Salle des Pompes. Tu entres dans la salle au bout du couloir."


def _room_scene(room=ROOM, room_category="DESC") -> list[str]:
    gold = [
        {
            "surface": "Salle des Pompes",
            "category": "REVEAL",
            "expected": "ALIAS location_salle_au_bout_du_couloir true_name",
        },
        {
            "surface": "la salle au bout du couloir",
            "category": room_category,
            "expected": "MATCH location_salle_au_bout_du_couloir",
        },
    ]
    effects = {
        "reveals": [
            {
                "ref": "location_salle_au_bout_du_couloir",
                "real_name": "Salle des Pompes",
            }
        ],
        "merges": [],
        "forbidden_merges": [],
    }
    return _custom_errors(BADGE, gold, world_extra=[room], gold_effects=effects)


def test_a_nameless_location_can_be_revealed():
    assert _room_scene() == []


def test_a_nameless_entity_must_have_known_false():
    errors = _room_scene(room={**ROOM, "known": True})
    assert any("known" in e and "world" in e for e in errors)


def test_the_label_of_a_nameless_entity_is_a_descriptor_not_an_easy_name():
    errors = _room_scene(room_category="EASY")
    assert len(errors) == 1 and "EASY" in errors[0]


def test_a_personal_pronoun_is_never_a_mention():
    narration = "Elle cligne des yeux."
    errors = _custom_errors(
        narration,
        [
            {
                "surface": "Elle",
                "category": "DESC",
                "expected": "MATCH character_kethari_agee",
            }
        ],
    )
    assert len(errors) == 1 and "pronoun" in errors[0]


def test_an_indefinite_pronoun_is_skip():
    narration = "Il y a quelqu'un devant toi."
    errors = _custom_errors(
        narration,
        [
            {
                "surface": "quelqu'un",
                "category": "DESC",
                "expected": "MATCH character_kethari_agee",
            }
        ],
    )
    assert len(errors) == 1 and "SKIP" in errors[0]
    assert (
        _custom_errors(
            narration,
            [{"surface": "quelqu'un", "category": "SKIP", "expected": "SKIP"}],
        )
        == []
    )


def test_an_unannotated_indefinite_pronoun_is_reported():
    errors = _custom_errors("Il y a quelqu'un devant toi.", [])
    assert len(errors) == 1 and "quelqu'un" in errors[0]


# --- scorer review: accept_also stays on the gold entity (ANNOTATION § 4.3) ---


def test_accept_also_must_name_the_expected_entity():
    errors = _errors(gold=_with_gold(0, accept_also=["MATCH protagonist_valentin"]))
    assert len(errors) == 1 and "accept_also" in errors[0]
    assert "protagonist_valentin" in errors[0]


def test_accept_also_cannot_be_new_or_skip():
    for alternative in ("NEW character", "SKIP"):
        errors = _errors(gold=_with_gold(0, accept_also=[alternative]))
        assert len(errors) == 1 and alternative in errors[0]


def test_accept_also_on_the_same_entity_is_valid():
    accept = ["ALIAS character_kethari_agee descriptor"]
    assert _errors(gold=_with_gold(0, accept_also=accept)) == []


# --- split and frozen test fingerprint (D25) ---

# Below this many mentions a category cannot hold a 35-45 % test share (one scene moves
# several mentions at once): the band is checked once the category is that large.
SPLIT_BAND_MIN_MENTIONS = 20


def _share_errors(scenes, split) -> list[str]:
    errors = []
    for category, (in_test, total) in shares_in_test(scenes, split).items():
        large = category in HARD_CATEGORIES and total >= SPLIT_BAND_MIN_MENTIONS
        if large and not 0.35 <= in_test / total <= 0.45:
            errors.append(f"{category}: {in_test}/{total} mentions in test")
    return errors


# Spec § 3.3: >= 50 mentions per hard category. Once a split is frozen (non-empty, the
# fingerprint is not the empty digest) every hard category must reach it, so the band
# above applies to all six and the check cannot stay vacuous.
FROZEN_MIN_MENTIONS = 50
EMPTY_DIGEST = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def _coverage_errors(scenes, split, frozen: str) -> list[str]:
    if not split.test or frozen == EMPTY_DIGEST:
        return []
    shares = shares_in_test(scenes, split)
    return [
        f"{c}: {shares.get(c, (0, 0))[1]} mentions, {FROZEN_MIN_MENTIONS} needed"
        for c in HARD_CATEGORIES
        if shares.get(c, (0, 0))[1] < FROZEN_MIN_MENTIONS
    ]


def test_frozen_test_split_fingerprint_matches():
    frozen = (ROOT / "TEST_SHA256").read_text(encoding="utf-8").strip()
    assert corpus.fingerprint_test_split(ROOT) == frozen, (
        "the test split changed: a gold correction of the test needs its own PR "
        "(ANNOTATION.md § 12), then scripts/identity_corpus_split.py --freeze"
    )


def test_split_is_stratified_and_disjoint():
    scenes = load_scenes(ROOT)
    split = load_split(ROOT)
    assert not set(split.dev) & set(split.test)
    assert sorted(split.dev + split.test) == sorted(s.id for s in scenes)
    assert _share_errors(scenes, split) == []
    frozen = (ROOT / "TEST_SHA256").read_text(encoding="utf-8").strip()
    assert _coverage_errors(scenes, split, frozen) == []


def _synthetic_scene(
    scene_id: str, categories: list[str], campaign: str | None = None
) -> Scene:
    gold = [
        {"surface": "x", "start": i, "category": c, "expected": "SKIP"}
        for i, c in enumerate(categories)
    ]
    return Scene.model_validate(
        _scene(id=scene_id, gold=gold, campaign=campaign or scene_id)
    )


def test_stratified_split_holds_each_category_share_on_a_synthetic_corpus():
    rng = random.Random(7)
    pool = [*HARD_CATEGORIES, "EASY", "EASY", "PC", "SKIP"]
    scenes = [
        _synthetic_scene(f"s{i:03}", rng.choices(pool, k=rng.randint(2, 8)))
        for i in range(110)
    ]
    split = stratified_split(scenes, ratio=0.6, seed=42)
    assert _share_errors(scenes, split) == []
    assert sorted(split.dev + split.test) == sorted(s.id for s in scenes)
    assert 0.3 <= len(split.test) / len(scenes) <= 0.5
    assert stratified_split(list(reversed(scenes)), ratio=0.6, seed=42) == split


def test_split_script_writes_the_split_and_its_fingerprint(tmp_path):
    import yaml

    from scripts.identity_corpus_split import main

    (tmp_path / "scenes").mkdir()
    for i in range(5):
        data = _scene(id=f"s{i}", campaign=f"c{i}")
        text = yaml.safe_dump(data, allow_unicode=True)
        (tmp_path / "scenes" / f"s{i}.yaml").write_text(text, encoding="utf-8")
    assert main(["--root", str(tmp_path), "--freeze"]) == 0
    split = load_split(tmp_path)
    assert sorted(split.dev + split.test) == [f"s{i}" for i in range(5)]
    frozen = (tmp_path / "TEST_SHA256").read_text(encoding="utf-8").strip()
    assert frozen == corpus.fingerprint_test_split(tmp_path)
    (tmp_path / "scenes" / f"{split.test[0]}.yaml").write_text("id: x\n")
    assert corpus.fingerprint_test_split(tmp_path) != frozen


def test_a_frozen_split_needs_fifty_mentions_per_hard_category():
    scenes = [_synthetic_scene(f"s{i}", ["PART", "DESC"]) for i in range(4)]
    split = stratified_split(scenes, ratio=0.6, seed=42)
    assert _coverage_errors(scenes, split, EMPTY_DIGEST) == []
    errors = _coverage_errors(scenes, split, "0" * 64)
    assert len(errors) == 6 and errors[0].startswith("PART: 4 mentions")


def _write_scenes(root, ids, *, names=None) -> None:
    import yaml

    (root / "scenes").mkdir()
    for scene_id, name in zip(ids, names or ids, strict=True):
        text = yaml.safe_dump(_scene(id=scene_id), allow_unicode=True)
        (root / "scenes" / f"{name}.yaml").write_text(text, encoding="utf-8")


def test_fingerprint_ignores_line_endings(tmp_path):
    _write_scenes(tmp_path, ["s0"])
    (tmp_path / "split.yaml").write_text("dev: []\ntest: [s0]\n", encoding="utf-8")
    lf = corpus.fingerprint_test_split(tmp_path)
    path = tmp_path / "scenes" / "s0.yaml"
    path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    assert corpus.fingerprint_test_split(tmp_path) == lf


def test_scene_file_name_must_be_its_id(tmp_path):
    _write_scenes(tmp_path, ["s0", "s1"], names=["s0", "other"])
    errors = corpus.file_name_errors(tmp_path)
    assert len(errors) == 1 and "other.yaml" in errors[0] and "'s1'" in errors[0]


def test_committed_scene_files_are_named_after_their_id():
    assert corpus.file_name_errors(ROOT) == []


def test_split_script_refuses_a_file_not_named_after_its_scene(tmp_path):
    from scripts.identity_corpus_split import main

    _write_scenes(tmp_path, ["s0"], names=["other"])
    assert main(["--root", str(tmp_path), "--freeze"]) == 1
    assert not (tmp_path / "split.yaml").exists()


# --- ruling (a): an entity born in the turn, then mentioned again (SAME <start>) ---

BORN = "Une femme au manteau gris entre. La femme au manteau gris sourit. Mira rit."
BORN_NEW = {"surface": "Une femme au manteau gris", "category": "NEW",
            "expected": "NEW character"}  # fmt: skip


def _born(repeat: dict, *, first: dict = BORN_NEW, **kwargs) -> list[str]:
    return _custom_errors(BORN, [first, repeat], **kwargs)


def _repeat(category="DESC", expected="SAME 0", **extra) -> dict:
    return {"surface": "La femme au manteau gris", "category": category,
            "expected": expected, **extra}  # fmt: skip


def test_a_repeat_of_an_entity_born_in_the_turn_is_same():
    assert _born(_repeat()) == []


def test_same_must_point_at_an_earlier_new_mention():
    later = {**_repeat(), "start": 0, "surface": "Une femme au manteau gris"}
    first = {**BORN_NEW, "start": BORN.index("La femme"),
             "surface": "La femme au manteau gris"}  # fmt: skip
    errors = _custom_errors(
        BORN, [{**later, "expected": f"SAME {BORN.index('La femme')}"}, first]
    )
    assert len(errors) == 1 and "earlier" in errors[0]
    errors = _born(_repeat(expected="SAME 3"))
    assert len(errors) == 1 and "SAME 3" in errors[0]
    linked = {**BORN_NEW, "category": "DESC",
              "expected": "MATCH character_kethari_agee"}  # fmt: skip
    errors = _born(_repeat(), first=linked)
    assert len(errors) == 1 and "NEW" in errors[0]


def test_same_takes_the_category_of_its_surface():
    for category in ("NEW", "GAP", "REVEAL", "XTYPE", "PC", "SKIP"):
        errors = _born(_repeat(category=category))
        assert errors and any(category in e for e in errors), category
    assert _born(_repeat(category="PART")) == []


def test_a_name_given_to_an_entity_born_in_the_turn_can_be_an_easy_same():
    text = "Une femme entre. — Mira, dit-elle."
    gold = [{"surface": "Une femme", "category": "NEW", "expected": "NEW character"},
            {"surface": "Mira", "category": "EASY", "expected": "SAME 0"}]  # fmt: skip
    assert _custom_errors(text, gold) == []


def test_same_has_no_accept_also_and_is_never_an_alternative():
    errors = _born(_repeat(accept_also=["MATCH character_kethari_agee"]))
    assert len(errors) == 1 and "accept_also" in errors[0]
    errors = _errors(gold=_with_gold(0, accept_also=["SAME 0"]))
    assert len(errors) == 1 and "accept_also" in errors[0]


def test_history_mentions_cannot_be_same():
    history = [{"text": BORN, "mentions": [
        {**BORN_NEW, "start": 0, "category": "DESC",
         "expected": "MATCH character_kethari_agee"},
        {**_repeat(), "start": BORN.index("La femme")},
    ]}]  # fmt: skip
    errors = _errors(history=history)
    assert len(errors) == 1 and "history" in errors[0]


def test_a_same_mention_is_in_the_cluster_of_its_new_mention():
    gold = [{**BORN_NEW, "start": 0},
            {**_repeat(), "start": BORN.index("La femme")}]  # fmt: skip
    turn = _custom(BORN, gold, id="seq-t1")
    repeat = f"seq-t1:{BORN.index('La femme')}"
    ok = Sequence.model_validate(
        {"id": "seq", "turns": [turn],
         "gold_clusters": {"character_femme": ["seq-t1:0", repeat]}}
    )  # fmt: skip
    assert validate_sequence(ok) == []
    split = Sequence.model_validate(
        {"id": "seq", "turns": [turn],
         "gold_clusters": {"character_femme": ["seq-t1:0"], "character_x": [repeat]}}
    )  # fmt: skip
    errors = validate_sequence(split)
    assert len(errors) == 1 and repeat in errors[0]


# --- ruling (b) and (d): nameless things are described; forms of a revealed name ---


def test_part_is_refused_on_an_entity_whose_name_the_pc_does_not_know():
    text = "Tu entres dans la salle."
    gold = [{"surface": "la salle", "category": "PART",
             "expected": "MATCH location_salle_au_bout_du_couloir"}]  # fmt: skip
    errors = _custom_errors(text, gold, world_extra=[ROOM])
    assert len(errors) == 1 and "DESC" in errors[0]
    gold[0]["category"] = "DESC"
    assert _custom_errors(text, gold, world_extra=[ROOM]) == []


def test_a_form_of_a_name_revealed_in_the_turn_is_part_alias_short():
    text = "Le badge dit : Salle des Pompes. Tu entres dans la salle."
    reveal = {
        "surface": "Salle des Pompes",
        "category": "REVEAL",
        "expected": "ALIAS location_salle_au_bout_du_couloir true_name",
    }
    effects = {"reveals": [{"ref": "location_salle_au_bout_du_couloir",
                            "real_name": "Salle des Pompes"}],
               "merges": [], "forbidden_merges": []}  # fmt: skip
    short = {"surface": "la salle", "start": text.index("la salle"), "category": "PART",
             "expected": "ALIAS location_salle_au_bout_du_couloir short",
             "accept_also": ["MATCH location_salle_au_bout_du_couloir"]}  # fmt: skip
    kwargs = {"world_extra": [ROOM], "gold_effects": effects}
    assert _custom_errors(text, [reveal, short], **kwargs) == []
    bare = {**short, "expected": "MATCH location_salle_au_bout_du_couloir",
            "accept_also": []}  # fmt: skip
    errors = _custom_errors(text, [reveal, bare], **kwargs)
    assert len(errors) == 1 and "ALIAS" in errors[0] and "short" in errors[0]


def test_a_new_label_is_part_and_a_fresh_object_nickname_is_desc():
    kettle = _entity("object_gourde", "object", "Gourde")
    text = "On l'appelle la Bouilloire. Les Passeurs Libres votent."
    guild = _entity("organization_guilde_des_passeurs", "organization",
                    "Guilde des Passeurs")  # fmt: skip
    gold = [
        {"surface": "la Bouilloire", "category": "DESC",
         "expected": "ALIAS object_gourde nickname"},
        {"surface": "Les Passeurs Libres", "category": "PART",
         "expected": "ALIAS organization_guilde_des_passeurs label"},
    ]  # fmt: skip
    kwargs = {"world_extra": [kettle, guild]}
    assert _custom_errors(text, gold, **kwargs) == []
    wrong = [{**gold[0], "category": "PART"}, {**gold[1], "category": "DESC"}]
    errors = _custom_errors(text, wrong, **kwargs)
    assert len(errors) == 2
    assert "nickname" in errors[0] and "label" in errors[1]


# --- coverage targets of the committed corpus (ANNOTATION § 8, spec § 3.3) ---

MIN_PER_CATEGORY = {"EASY": 100, "SKIP": 60, "PC": 30} | dict.fromkeys(
    HARD_CATEGORIES, 50
)
TYPED = ("character", "location", "organization", "object")
MIN_TYPE_SHARE = 0.15
KNOWLEDGE_TYPES = (*TYPED, "arc")
REQUIRED_SCENES = ("issue-25-voss", "issue-26-gap21", "roadmap-rizka-elara")
REQUIRED_PREFIXES = ("real-f134-",)


def _mention_type(scene: Scene, m) -> str:
    """Target type of a gold mention (a SAME takes the type of its NEW mention)."""
    expected = m.parsed
    if expected.decision == "SAME":
        expected = next(g for g in scene.gold if g.start == expected.same_start).parsed
    if expected.decision == "NEW":
        return expected.new_type
    entity = next((e for e in scene.world if e.id == expected.entity_id), None)
    return entity.type if entity is not None else "none"


def _coverage_target_errors(scenes: list[Scene]) -> list[str]:
    counts = Counter(m.category for s in scenes for m in s.gold)
    by_type = Counter((m.category, _mention_type(s, m)) for s in scenes for m in s.gold)
    errors = [
        f"{c}: {counts[c]} mentions, {n} needed"
        for c, n in MIN_PER_CATEGORY.items()
        if counts[c] < n
    ]
    for c in HARD_CATEGORIES:
        for t in TYPED:
            if counts[c] and by_type[(c, t)] / counts[c] < MIN_TYPE_SHARE:
                errors.append(f"{c} x {t}: {by_type[(c, t)]}/{counts[c]} under 15 %")
    if len({s.genre for s in scenes}) < 2:
        errors.append("fewer than two genres")
    states = set()
    for s in scenes:
        types = {e.id: e.type for e in s.world}
        states |= {(types.get(k.ref), k.state) for k in s.gold_knowledge}
    errors += [
        f"gold_knowledge has no {state} item on a {t}"
        for t in KNOWLEDGE_TYPES
        for state in ("unknown", "secret")
        if (t, state) not in states
    ]
    ids = {s.id for s in scenes}
    errors += [
        f"required scene {i} is missing" for i in REQUIRED_SCENES if i not in ids
    ]
    errors += [
        f"no scene {p}*"
        for p in REQUIRED_PREFIXES
        if not any(i.startswith(p) for i in ids)
    ]
    return errors


def test_corpus_meets_the_coverage_targets():
    # Scenes only: the per-category metrics never see the sequence turns (§ 8).
    assert _coverage_target_errors(load_scenes(ROOT)) == []


def test_coverage_targets_fail_on_a_thin_corpus():
    errors = _coverage_target_errors([Scene.model_validate(_scene())])
    assert any(e.startswith("PART: 0 mentions") for e in errors)
    assert "fewer than two genres" in errors
    assert "required scene issue-25-voss is missing" in errors
    assert "gold_knowledge has no secret item on a arc" in errors


# --- review I4 and M2: forms after a reveal, nameless test on names only ---

TESK_TWICE = "— Tesk Vahrun-Oo, dit-il. Tesk Vahrun-Oo, répète-t-il."


def _tesk_twice(accept: list[str]) -> list[str]:
    gold = [
        {"surface": "Tesk Vahrun-Oo", "category": "REVEAL",
         "expected": "ALIAS character_tesk true_name"},
        {"surface": "Tesk Vahrun-Oo", "start": TESK_TWICE.index("Tesk", 10),
         "category": "EASY", "expected": "ALIAS character_tesk true_name",
         "accept_also": accept},
    ]  # fmt: skip
    effects = {"reveals": [{"ref": "character_tesk", "real_name": "Tesk Vahrun-Oo"}],
               "merges": [], "forbidden_merges": []}  # fmt: skip
    return _custom_errors(TESK_TWICE, gold, world_extra=[TESK_OLD], turn=21,
                          gold_effects=effects, gold_knowledge=[TESK_NAME])  # fmt: skip


def test_a_full_name_repeated_after_a_reveal_accepts_a_plain_match():
    assert _tesk_twice(["MATCH character_tesk"]) == []
    errors = _tesk_twice([])
    assert len(errors) == 1 and "MATCH character_tesk" in errors[0]


def test_part_is_allowed_on_an_unknown_entity_with_a_known_title():
    titled = {**ROOM, "aliases": [*ROOM["aliases"],
              {"text": "la Salle", "kind": "title", "known": True}]}  # fmt: skip
    text = "Tu entres dans la salle."
    gold = [{"surface": "la salle", "category": "PART",
             "expected": "MATCH location_salle_au_bout_du_couloir"}]  # fmt: skip
    assert _custom_errors(text, gold, world_extra=[titled]) == []


# --- review I2: campaigns, a group-aware split, no leak through histories ---


def test_a_scene_needs_its_campaign():
    data = _scene()
    del data["campaign"]
    with pytest.raises(ValidationError):
        Scene.model_validate(data)


def test_the_split_keeps_each_campaign_on_one_side():
    rng = random.Random(3)
    pool = [*HARD_CATEGORIES, "EASY", "PC", "SKIP"]
    scenes = [
        _synthetic_scene(f"s{i:03}", rng.choices(pool, k=rng.randint(2, 8)),
                         campaign=f"c{i // 4}")
        for i in range(120)
    ]  # fmt: skip
    split = stratified_split(scenes, ratio=0.6, seed=42)
    side = {i: "test" for i in split.test} | {i: "dev" for i in split.dev}
    by_campaign: dict[str, set[str]] = {}
    for s in scenes:
        by_campaign.setdefault(s.campaign, set()).add(side[s.id])
    assert all(len(sides) == 1 for sides in by_campaign.values())
    assert _share_errors(scenes, split) == []
    assert stratified_split(list(reversed(scenes)), ratio=0.6, seed=42) == split


def test_no_test_narration_is_seen_from_the_dev_side():
    scenes = {s.id: s for s in load_scenes(ROOT)}
    split = load_split(ROOT)
    turns = [t for q in load_sequences(ROOT) for t in q.turns]
    for side, other in ((split.test, split.dev), (split.dev, split.test)):
        hidden = {scenes[i].narration for i in side}
        seen = [scenes[i] for i in other]
        if side is split.test:
            seen += turns  # sequences are used for coreference, never for the test
        leaks = [
            f"{s.id} history holds a narration of the other side"
            for s in seen
            for h in s.history
            if h.text in hidden
        ]
        leaks += [f"{s.id} repeats a narration of the other side"
                  for s in seen if s.narration in hidden]  # fmt: skip
        assert leaks == []


def test_scenes_sharing_a_history_share_a_campaign():
    scenes = load_scenes(ROOT)
    owner = {s.narration: s.campaign for s in scenes}
    mixed = [
        f"{s.id} ({s.campaign}) shows a narration of {owner[h.text]}"
        for s in scenes
        for h in s.history
        if h.text in owner and owner[h.text] != s.campaign
    ]
    assert mixed == []


# --- final review I2: a sanctioned way to add a dev scene after the freeze ---


def test_add_dev_appends_a_new_scene_and_leaves_the_test_untouched(tmp_path):
    import yaml

    from scripts.identity_corpus_split import main

    (tmp_path / "scenes").mkdir()
    for i in range(6):
        data = _scene(id=f"s{i}", campaign=f"c{i}")
        text = yaml.safe_dump(data, allow_unicode=True)
        (tmp_path / "scenes" / f"s{i}.yaml").write_text(text, encoding="utf-8")
    assert main(["--root", str(tmp_path), "--freeze"]) == 0
    before = load_split(tmp_path)
    frozen = (tmp_path / "TEST_SHA256").read_text(encoding="utf-8")
    header = (tmp_path / "split.yaml").read_text(encoding="utf-8").split("dev:")[0]

    new = _scene(id="s9", campaign="c9")
    (tmp_path / "scenes" / "s9.yaml").write_text(
        yaml.safe_dump(new, allow_unicode=True), encoding="utf-8"
    )
    test_campaign = _scene(id="s8", campaign=f"c{before.test[0][1:]}")
    (tmp_path / "scenes" / "s8.yaml").write_text(
        yaml.safe_dump(test_campaign, allow_unicode=True), encoding="utf-8"
    )
    assert main(["--root", str(tmp_path), "--add-dev", "s8"]) == 1  # a test campaign
    assert main(["--root", str(tmp_path), "--add-dev", "s0"]) == 1  # already split
    assert main(["--root", str(tmp_path), "--add-dev", "s9"]) == 0

    after = load_split(tmp_path)
    assert after.test == before.test and after.dev == sorted([*before.dev, "s9"])
    assert (tmp_path / "TEST_SHA256").read_text(encoding="utf-8") == frozen
    assert corpus.fingerprint_test_split(tmp_path) == frozen.strip()
    assert (tmp_path / "split.yaml").read_text(encoding="utf-8").startswith(header)


# --- re-review R1: the annotation guide cites no test-split material ---

_QUOTED = re.compile(r"«\s*([^»]+?)\s*»")


def _fold(text: str) -> str:
    return text.replace("*", "").replace("’", "'").strip().casefold()


def _guide_leaks(guide: str, test_scenes: list[Scene], allowed: set[str]) -> set[str]:
    """Quoted guide examples equal to a test surface or name (any case), and test ids.

    A string is a leak even when a dev scene also holds it: the guide would still give
    the decision of the test mention. Only the closed word lists (`allowed`) are exempt.
    """
    quoted = {_fold(q) for q in _QUOTED.findall(guide)}
    material = set()
    for s in test_scenes:
        material |= {m.surface for m in s.gold} | {e.label for e in s.world}
        material |= {a.text for e in s.world for a in e.aliases}
    leaks = {t for t in map(_fold, material) if t in quoted} - allowed
    return leaks | {s.id for s in test_scenes if s.id in guide}


def test_the_guide_cites_no_test_material():
    from evals.identity.lexicon import load_lexicon

    test_ids = set(load_split(ROOT).test)
    tests = [s for s in load_scenes(ROOT) if s.id in test_ids]
    guide = (ROOT / "ANNOTATION.md").read_text(encoding="utf-8")
    # § 12 reports on the blind review and may name the scenes it measured; the rules
    # (every other section) must not point at a test scene.
    head, _, rest = guide.partition("\n## 12.")
    guide = head + "\n## 13." + rest.partition("\n## 13.")[2]
    allowed = {_fold(w) for w in load_lexicon("fr").indefinite_pronouns}
    assert _guide_leaks(guide, tests, allowed) == set()


def test_the_guide_leak_check_ignores_case_and_dev_copies():
    scene = Scene.model_validate(_scene(id="t1"))
    guide = "Exemple : « la KETHARI âgée » (DESC)."
    assert _guide_leaks(guide, [scene], set()) == {"la kethari âgée"}
    assert _guide_leaks("Voir `t1`.", [scene], set()) == {"t1"}
    assert _guide_leaks("« sa paume »", [scene], {"sa paume"}) == set()


# --- the « carried » flag of the worlds (#154, ruling R39) ---------------------------


def test_every_world_follows_the_carried_rule():
    """`carried: true` is never set by hand: every scene and sequence turn holds exactly
    what the rule of evals/identity/carried.py gives (scripts/identity_corpus_carried.py)."""
    counts, changed = identity_corpus_carried.apply(ROOT, check=True)
    assert changed == []
    assert counts["dev"] > 0


def test_the_carried_rule_reads_second_person_possessives_of_names_and_history():
    lantern = {"id": "object_lanterne", "type": "object", "label": "Lanterne de cuivre",
               "known": True, "aliases": [{"text": "ta lanterne", "kind": "descriptor",
                                           "known": True}]}  # fmt: skip
    box = {"id": "object_boite", "type": "object", "label": "Boîte grise", "known": True,
           "aliases": [{"text": "Boîte grise", "kind": "label", "known": True}]}  # fmt: skip
    hers = {"id": "object_bague", "type": "object", "label": "Bague", "known": True,
            "aliases": [{"text": "Bague", "kind": "label", "known": True}]}  # fmt: skip
    data = _scene()
    history = [{"text": "Tu poses ta boîte. Elle tourne sa bague.", "mentions": [
        {"surface": "ta boîte", "start": 8, "category": "DESC",
         "expected": "MATCH object_boite"},
        {"surface": "sa bague", "start": 30, "category": "DESC",
         "expected": "MATCH object_bague"},
    ]}]  # fmt: skip
    scene = Scene.model_validate(
        {**data, "world": [*data["world"], lantern, box, hers], "history": history}
    )
    assert carried_objects(scene) == {"object_lanterne", "object_boite"}
    with pytest.raises(ValidationError, match="objects only"):
        Scene.model_validate(
            {**data, "world": [{**data["world"][1], "carried": True}, *data["world"]]}
        )


def test_every_corpus_language_has_second_person_possessives():
    """The carried rule needs the list: a language without it would flag nothing."""
    from evals.identity.lexicon import load_lexicon

    languages = {s.language for s in corpus.load_scenes(ROOT)}
    languages |= {t.language for q in corpus.load_sequences(ROOT) for t in q.turns}
    assert languages and all(
        load_lexicon(lang).second_person_possessives for lang in languages
    )


def test_a_true_name_needs_its_own_alias():
    world = _scene()["world"]
    bare = {"id": "character_ana", "type": "character", "label": "Ana Ferro",
            "true_name": "Ana Ferro", "known": False, "aliases": []}  # fmt: skip
    errors = _errors(world=[*world, bare])
    assert any("true_name has no alias of its own" in e for e in errors)
