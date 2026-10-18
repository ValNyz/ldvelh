"""info_requests details live for exactly one turn (#64): requested at A, injected at B,
gone at C unless B asks again. The set is part of the turn's commit and of rollback."""

import json

import pytest

from tests.characterization import payloads
from tests.characterization.harness import spy_narration

pytestmark = pytest.mark.integration

HEADER = "### DÉTAILS DEMANDÉS"
PLACE = "Le Quart de Cycle"


def _narration(**extra) -> str:
    data = json.loads(payloads.NARRATION)
    data.update(extra)
    return json.dumps(data, ensure_ascii=False)


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
    await _turn(harness, world_game, _narration(info_requests=[PLACE]))  # A: asks
    await _turn(harness, world_game, _narration(info_requests=[PLACE]))  # B: injected, asks again
    await _turn(harness, world_game, _narration())                       # C: injected, no ask
    await _turn(harness, world_game, _narration())                       # D: dropped
    seen = [HEADER in str(c["messages"][-1]) for c in calls]
    assert seen == [False, True, True, False]
    assert await _stored(harness, world_game) == []


async def test_request_at_c_without_one_at_b_is_injected_at_d(harness, world_game, monkeypatch):
    calls = spy_narration(monkeypatch)
    await _turn(harness, world_game, _narration(info_requests=[PLACE]))  # A
    await _turn(harness, world_game, _narration())                       # B: injected
    await _turn(harness, world_game, _narration(info_requests=[PLACE]))  # C: absent, asks
    await _turn(harness, world_game, _narration())                       # D: injected
    assert [HEADER in str(c["messages"][-1]) for c in calls] == [False, True, False, True]


async def test_new_requests_replace_the_consumed_ones(harness, world_game):
    await _turn(harness, world_game, _narration(info_requests=[PLACE]))
    await _turn(harness, world_game, _narration(info_requests=["Ossek"]))
    assert await _stored(harness, world_game) == ["Ossek"]


async def _rollback_last_turn(harness, game_id):
    async with harness.pool.acquire() as conn:
        user_msg = await conn.fetchval(
            """SELECT id FROM messages WHERE game_id = $1 AND role = 'user'
               ORDER BY created_at DESC, sequence DESC LIMIT 1""", game_id)
    r = await harness.client.post(f"/api/games/{game_id}/rollback",
                                  json={"messageId": str(user_msg)}, headers=harness.headers)
    assert r.status_code == 200, r.text


async def test_rollback_of_consuming_turn_makes_details_available_again(harness, world_game):
    await _turn(harness, world_game, _narration(info_requests=[PLACE]))  # A
    await _turn(harness, world_game, _narration())                       # B consumes
    assert await _stored(harness, world_game) == []
    await _rollback_last_turn(harness, world_game)                       # undo B
    assert await _stored(harness, world_game) == [PLACE]


async def test_rollback_of_requesting_turn_drops_its_requests(harness, world_game):
    await _turn(harness, world_game, _narration())                       # A: nothing
    await _turn(harness, world_game, _narration(info_requests=[PLACE]))  # B asks
    assert await _stored(harness, world_game) == [PLACE]
    await _rollback_last_turn(harness, world_game)                       # undo B
    assert await _stored(harness, world_game) == []
