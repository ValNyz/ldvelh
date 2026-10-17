"""Fate aspect invocation on a stored roll: pure computation and validation (#32)."""

import pytest

from domain.errors import TurnError
from domain.turn import InvocationOffer
from schema.engine import RollResult
from services.engine import get_engine
from services.engine.fate_core import aspect_names, outcome_for_shifts

ASPECTS = ["Pilote déchu", "Dette envers la Guilde", "Réflexes de contrebandier"]


def _failed_roll(skill_total=1, difficulty=2):
    """Original stored roll: four dice, skill_total vs difficulty (failure by default)."""
    shifts = skill_total - difficulty
    return RollResult(dice=[-1, 0, 0, 0], total=-1, skill_total=skill_total,
                      outcome=outcome_for_shifts(shifts), shifts=shifts,
                      details={"skill_name": "Athlétisme", "difficulty": difficulty})


def _invoke(roll, invoked, fate_points=3, aspects=ASPECTS):
    return get_engine("fate_core").apply_invocation(roll, invoked, aspects, fate_points)


def test_invocation_adds_two_per_aspect_and_recomputes_outcome():
    roll = _failed_roll()
    assert roll.outcome == "failure"

    one = _invoke(roll, ["Pilote déchu"])
    assert (one.skill_total, one.shifts, one.outcome) == (3, 1, "success")
    assert one.details["fate_points_spent"] == 1
    assert one.details["invocation_bonus"] == 2
    assert one.details["invoked_aspects"] == ["Pilote déchu"]
    assert one.details["difficulty"] == 2

    two = _invoke(roll, ["Pilote déchu", "Dette envers la Guilde"], fate_points=2)
    assert (two.skill_total, two.shifts, two.outcome) == (5, 3, "success_with_style")
    assert two.details["fate_points_spent"] == 2
    # The original roll is never modified: every computation starts from it.
    assert (roll.skill_total, roll.outcome, "invoked_aspects" in roll.details) == (1, "failure", False)


def test_duplicates_count_once():
    result = _invoke(_failed_roll(), ["Pilote déchu", "pilote dechu", "Pilote déchu"], fate_points=1)
    assert result.details["invoked_aspects"] == ["Pilote déchu"]
    assert result.details["fate_points_spent"] == 1
    assert result.skill_total == 3


def test_unknown_aspect_is_rejected():
    with pytest.raises(TurnError) as exc:
        _invoke(_failed_roll(), ["Pilote déchu", "Chanceux"])
    assert exc.value.code == "invalid_invocation"
    assert exc.value.message == "Aspect inconnu : Chanceux."


def test_more_aspects_than_fate_points_is_rejected():
    with pytest.raises(TurnError) as exc:
        _invoke(_failed_roll(), ["Pilote déchu", "Dette envers la Guilde"], fate_points=1)
    assert exc.value.code == "invalid_invocation"
    assert exc.value.message == "Pas assez de points de destin (1) pour 2 invocations."


def test_tie_and_failure_after_invocation():
    tie = _invoke(_failed_roll(skill_total=0, difficulty=2), ["Pilote déchu"])
    assert (tie.skill_total, tie.shifts, tie.outcome) == (2, 0, "tie")
    still_failed = _invoke(_failed_roll(skill_total=-4, difficulty=4), ["Pilote déchu"])
    assert (still_failed.skill_total, still_failed.shifts, still_failed.outcome) == (-2, -6, "failure")


def test_outcome_ladder_is_shared_with_roll_dice():
    assert [outcome_for_shifts(s) for s in (-1, 0, 1, 2, 3)] == [
        "failure", "tie", "success", "success", "success_with_style"]


def test_aspect_names_accepts_strings_and_dicts():
    stats = {"aspects": ["Pilote", {"name": "Dette", "type": "trouble"}, {"text": "Réflexes"}, "", {}]}
    assert aspect_names(stats) == ["Pilote", "Dette", "Réflexes"]
    assert aspect_names({}) == []


def test_invoked_aspects_take_the_sheet_spelling():
    result = _invoke(_failed_roll(), ["pilote dechu", "DETTE ENVERS LA GUILDE"])
    assert result.details["invoked_aspects"] == ["Pilote déchu", "Dette envers la Guilde"]


# -- engine contract: when a failed roll may wait for an invocation (#78) -------------

SHEET = {"aspects": ASPECTS, "fate_points": 2}


def test_fate_offers_invocation_on_a_failed_roll():
    offer = get_engine("fate_core").invocation_offer(_failed_roll(), SHEET)
    assert offer == InvocationOffer(aspects=ASPECTS, fate_points=2)


@pytest.mark.parametrize("roll, sheet", [
    (_failed_roll(skill_total=3, difficulty=2), SHEET),     # success
    (_failed_roll(), {"aspects": ASPECTS, "fate_points": 0}),
    (_failed_roll(), {"aspects": [], "fate_points": 2}),
    (_failed_roll(), None),
])
def test_fate_offers_nothing_without_failure_points_or_aspects(roll, sheet):
    assert get_engine("fate_core").invocation_offer(roll, sheet) is None


@pytest.mark.parametrize("engine", ["d6", "narrative", "none"])
def test_other_engines_never_offer_invocation(engine):
    assert get_engine(engine).invocation_offer(_failed_roll(), SHEET) is None
    assert get_engine(engine).available_invocations(SHEET) == InvocationOffer(aspects=[],
                                                                               fate_points=0)


def test_fate_available_invocations_read_the_sheet():
    engine = get_engine("fate_core")
    assert engine.available_invocations(SHEET) == InvocationOffer(aspects=ASPECTS, fate_points=2)
    assert engine.available_invocations(None) == InvocationOffer(aspects=[], fate_points=0)
