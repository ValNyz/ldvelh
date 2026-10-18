"""info_requests details live for exactly one turn (#64): requested at A, injected at B,
gone at C unless B asks again. The set is part of the turn's commit and of rollback."""

import pytest

from services.game_service import _stored_info_requests
from tests.characterization.harness import spy_narration
from tests.helpers import narration_with, rollback_last_turn

pytestmark = pytest.mark.integration

HEADER = "### DÉTAILS DEMANDÉS"
PLACE = "Le Quart de Cycle"


async def _turn(harness, game_id, narration_json, message="Je continue."):
    harness.llm._responses["narration"] = narration_json
    events = await harness.chat(game_id, message)
    await harness.drain()
    return events


async def _stored(harness, game_id):
    async with harness.pool.acquire() as conn:
        return list(await conn.fetchval("SELECT detail_requests FROM games WHERE id = $1", game_id))


async def test_details_injected_one_turn_unless_requested_again(harness, world_game, monkeypatch):
    calls = spy_narration(monkeypatch)
    await _turn(harness, world_game, narration_with(info_requests=[PLACE]))  # A: asks
    await _turn(harness, world_game, narration_with(info_requests=[PLACE]))  # B: injected, asks again
    await _turn(harness, world_game, narration_with())                       # C: injected, no ask
    await _turn(harness, world_game, narration_with())                       # D: dropped
    seen = [HEADER in str(c["messages"][-1]) for c in calls]
    assert seen == [False, True, True, False]
    assert await _stored(harness, world_game) == []


async def test_request_at_c_without_one_at_b_is_injected_at_d(harness, world_game, monkeypatch):
    calls = spy_narration(monkeypatch)
    await _turn(harness, world_game, narration_with(info_requests=[PLACE]))  # A
    await _turn(harness, world_game, narration_with())                       # B: injected
    await _turn(harness, world_game, narration_with(info_requests=[PLACE]))  # C: absent, asks
    await _turn(harness, world_game, narration_with())                       # D: injected
    assert [HEADER in str(c["messages"][-1]) for c in calls] == [False, True, False, True]


async def test_new_requests_replace_the_consumed_ones(harness, world_game):
    await _turn(harness, world_game, narration_with(info_requests=[PLACE]))
    await _turn(harness, world_game, narration_with(info_requests=["Ossek"]))
    assert await _stored(harness, world_game) == ["Ossek"]


async def test_rollback_of_consuming_turn_makes_details_available_again(harness, world_game):
    await _turn(harness, world_game, narration_with(info_requests=[PLACE]))  # A
    await _turn(harness, world_game, narration_with())                       # B consumes
    assert await _stored(harness, world_game) == []
    await rollback_last_turn(harness, world_game)                            # undo B
    assert await _stored(harness, world_game) == [PLACE]


async def test_rollback_of_requesting_turn_drops_its_requests(harness, world_game):
    await _turn(harness, world_game, narration_with())                       # A: nothing
    await _turn(harness, world_game, narration_with(info_requests=[PLACE]))  # B asks
    assert await _stored(harness, world_game) == [PLACE]
    await rollback_last_turn(harness, world_game)                            # undo B
    assert await _stored(harness, world_game) == []


async def test_failed_turn_keeps_the_pending_requests(harness, world_game, monkeypatch):
    from repos import turns

    await _turn(harness, world_game, narration_with(info_requests=[PLACE]))  # A asks

    async def boom(*args, **kwargs):
        raise RuntimeError("commit failed")

    monkeypatch.setattr(turns, "save_turn_messages", boom)
    await _turn(harness, world_game, narration_with())                       # B: commit fails
    assert await _stored(harness, world_game) == [PLACE]


async def test_rollback_to_a_message_without_the_key_restores_nothing(harness, world_game):
    await _turn(harness, world_game, narration_with())                       # A
    await _turn(harness, world_game, narration_with(info_requests=[PLACE]))  # B asks
    async with harness.pool.acquire() as conn:
        await conn.execute(  # messages as saved before #64: no info_requests key
            "UPDATE messages SET narrator_deltas = narrator_deltas - 'info_requests'"
            " WHERE game_id = $1", world_game)
    await _turn(harness, world_game, narration_with(info_requests=["Ossek"]))  # C asks
    assert await _stored(harness, world_game) == ["Ossek"]
    await rollback_last_turn(harness, world_game)                            # undo C: keep B
    assert await _stored(harness, world_game) == []


@pytest.mark.parametrize("raw, expected", [
    ({"info_requests": ["A", "B"]}, ["A", "B"]),
    ('{"info_requests": ["A"]}', ["A"]),
    ({}, []),
    (None, []),
    ("not json", []),
    ({"info_requests": None}, []),
    ({"info_requests": ["A", 3, None]}, ["A"]),
])
def test_stored_info_requests_tolerates_any_stored_shape(raw, expected):
    assert _stored_info_requests(raw) == expected
