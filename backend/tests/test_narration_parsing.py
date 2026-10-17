"""Lenient narration parsing (#16, #44): odd optional fields never discard the turn."""

import pytest

from helpers import apply_state
from schema.narration import NarrationInvalid, parse_narration
from tests.test_game_and_populator import _make_narration_output, _setup_game_with_world

_KW = dict(current_time="10h00", current_location="Le Quart de Cycle")


def _raw(**extra) -> dict:
    data = _make_narration_output("Le Quart de Cycle")
    data.pop("credit_delta")
    data.update(extra)
    return data


@pytest.mark.integration
@pytest.mark.parametrize("shape, expected_date", [
    (True, "Jour 2"),
    ("Mardi", "Mardi"),
    ({"new_date": "Mardi"}, "Mardi"),
    ({"new_cycle": 9, "new_date": "Mardi"}, "Mardi"),
    ({"new_cycle": "abc", "new_date": "Mardi"}, "Mardi"),
    ({"new_date": 5}, "5"),
    ({"night_summary": ["x"], "new_date": "Mardi"}, "Mardi"),
    ({"night_summary": {"a": 1}}, "Jour 2"),
    (1, "Jour 2"),
    ("oui", "oui"),
    ([1], "Jour 2"),
    ({}, "Jour 2"),
], ids=["true", "string", "date_only", "new_cycle_ignored", "new_cycle_text", "date_number",
        "summary_list", "summary_dict", "one", "yes", "list", "empty_dict"])
async def test_day_transition_shapes_advance_one_day(
        client, test_user, test_pool, shape, expected_date):
    game_id, service, _ = await _setup_game_with_world(client, test_user, test_pool)
    narration, dropped = parse_narration(_raw(day_transition=shape), **_KW)
    assert dropped == []

    result = await apply_state(test_pool, game_id, narration, 1)

    assert result.cycle == 2
    assert result.date == expected_date
    state = await service.load_game_state(game_id)
    assert state["game"]["current_cycle"] == 2
    assert state["game"]["game_date"] == expected_date


def test_invalid_optional_field_is_dropped_not_the_turn():
    narration, dropped = parse_narration(
        _raw(credit_delta={"amount": "beaucoup"}), **_KW)
    assert dropped == ["credit_delta"]
    assert narration.credit_delta is None
    assert narration.narrative_text


def test_missing_time_and_location_are_filled():
    data = _raw()
    del data["time"], data["current_location"]
    narration, dropped = parse_narration(data, **_KW)
    assert dropped == []
    assert narration.time.new_time == "10h00"
    assert narration.current_location == "Le Quart de Cycle"


def test_missing_narrative_text_is_invalid():
    data = _raw()
    del data["narrative_text"]
    with pytest.raises(NarrationInvalid):
        parse_narration(data, **_KW)


@pytest.mark.parametrize("shape", [False, None, 0, 0.0, "", "null", "false", "none", "aucune",
                                   "non", "no", " NULL ", "Aucune", "False"])
def test_false_and_null_day_transition_mean_no_transition(shape):
    narration, dropped = parse_narration(_raw(day_transition=shape), **_KW)
    assert dropped == []
    assert narration.day_transition is None


def test_non_object_output_is_invalid():
    with pytest.raises(NarrationInvalid):
        parse_narration(["not", "an", "object"], **_KW)


def test_invalid_required_field_alongside_optional_is_invalid():
    # credit_delta is droppable but time is not: nothing is salvaged.
    with pytest.raises(NarrationInvalid):
        parse_narration(_raw(credit_delta={"amount": "x"}, time={"ellipse": False}), **_KW)


def test_narrate_validate_rejects_non_object_as_narration_invalid():
    from types import SimpleNamespace

    from pipeline.steps.narrate import _validate

    ctx = SimpleNamespace(snapshot=SimpleNamespace(current_time="10h00",
                                                   current_location_name="Ici"))
    with pytest.raises(NarrationInvalid):
        _validate(ctx, [{"narrative_text": "x"}])
