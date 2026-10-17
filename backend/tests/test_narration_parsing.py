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
], ids=["true", "string", "date_only", "new_cycle_ignored"])
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
