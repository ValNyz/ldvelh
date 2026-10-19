"""Identity gold corpus: format, loader and validation (#151)."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from evals.identity.corpus import (
    Scene,
    Sequence,
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
