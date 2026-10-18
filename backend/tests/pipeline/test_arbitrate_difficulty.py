"""The wizard difficulty reaches the mechanical arbiter (#137)."""

import logging
from uuid import UUID

import pytest

from domain.game import DEFAULT_DIFFICULTY, difficulty_from_world_config
from pipeline.steps import arbitrate
from repos.games import get_snapshot
from tests.characterization import payloads


@pytest.fixture
def arbiter_inputs(monkeypatch):
    """Difficulty passed to run_mechanical_step on each call."""
    seen: list[str] = []
    original = arbitrate.run_mechanical_step

    async def spy(**kwargs):
        seen.append(kwargs["world_difficulty"])
        return await original(**kwargs)

    monkeypatch.setattr(arbitrate, "run_mechanical_step", spy)
    return seen


async def _roll_turn(harness, game_id: str):
    harness.llm._responses["mechanical"] = payloads.mechanical(
        requires_test=True, skill="Athlétisme", skill_value=2, difficulty=1)
    await harness.chat(game_id, "Je saute par-dessus la barrière.")
    await harness.drain()


async def test_hard_game_sends_hard(harness, test_pool, arbiter_inputs):
    game_id = await harness.create_game("fate_core")
    await harness.chat(game_id, "__INIT__", engine="fate_core",
                       world_config={"genre": "sci_fi", "difficulty": "hard"},
                       character_data=payloads.CHARACTER_DATA["fate_core"])
    await harness.drain()
    await harness.chat(game_id, "__ARRIVEE__")
    await harness.drain()
    await _roll_turn(harness, game_id)
    assert arbiter_inputs == ["hard"]


async def test_legacy_game_sends_moderate(harness, test_pool, fate_game, arbiter_inputs):
    async with test_pool.acquire() as conn:
        await conn.execute("UPDATE games SET world_config = NULL WHERE id = $1",
                           UUID(fate_game))
    await _roll_turn(harness, fate_game)
    assert arbiter_inputs == ["moderate"]


@pytest.mark.parametrize("config, expected, unknown", [
    ({"difficulty": "easy"}, "easy", False),
    ({"difficulty": "brutal"}, "brutal", False),
    (None, DEFAULT_DIFFICULTY, False),
    ({}, DEFAULT_DIFFICULTY, False),
    ({"difficulty": "nightmare"}, DEFAULT_DIFFICULTY, True),
    ("not-an-object", DEFAULT_DIFFICULTY, True),
    (["hard"], DEFAULT_DIFFICULTY, True),
])
def test_mapping_is_pure(config, expected, unknown):
    assert difficulty_from_world_config(config) == (expected, unknown)


async def test_unknown_value_warns_with_game_id_only(harness, test_pool, fate_game, caplog):
    async with test_pool.acquire() as conn:
        await conn.execute("UPDATE games SET world_config = $2 WHERE id = $1", UUID(fate_game),
                           {"difficulty": "nightmare-story"})
        with caplog.at_level(logging.WARNING, logger="repos.games"):
            snapshot = await get_snapshot(conn, UUID(fate_game))
    assert snapshot.difficulty == "moderate"
    assert fate_game in caplog.text
    assert "nightmare" not in caplog.text
