"""C-01..C-03: world generation, arrival scene, plain narration turn (engine none)."""

import pytest

from services.llm_providers import StructuredOutputMode
from tests.characterization.snapshot import assert_snapshot


async def test_c01_init_world(harness):
    game_id = await harness.create_game("none")
    events = await harness.init_world(game_id)
    assert_snapshot("c01_init", harness.snapshot(events, await harness.db_summary(game_id)))


async def test_c02_arrival(harness):
    game_id = await harness.create_game("none")
    await harness.init_world(game_id)
    harness.llm.calls.clear()
    events = await harness.chat(game_id, "__ARRIVEE__")
    await harness.drain()
    assert_snapshot("c02_arrival", harness.snapshot(events, await harness.db_summary(game_id)))


@pytest.mark.parametrize("llm_mode", [
    StructuredOutputMode.TOOL_USE,
    StructuredOutputMode.JSON_SCHEMA,
    StructuredOutputMode.TEXT,
], ids=["tool_use", "json_schema", "text"])
async def test_c03_light_turn(harness, world_game, llm_mode):
    events = await harness.chat(world_game, "Je regarde autour de moi.")
    await harness.drain()
    snap = harness.snapshot(events, await harness.db_summary(world_game))
    assert "done" in snap["sse"] and "error" not in snap["sse"]
    assert_snapshot(f"c03_light_turn[{llm_mode.value}]", snap)
