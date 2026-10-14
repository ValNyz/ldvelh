"""C-04..C-06: rule engines, Fate aspect invocation (pending roll + resume), compels."""

from types import SimpleNamespace

import pytest

from services import llm_service
from services.engine import fate_core
from tests.characterization import payloads
from tests.characterization.snapshot import assert_snapshot


async def _engine_game(harness, engine):
    game_id = await harness.create_game(engine)
    await harness.init_world(game_id, engine=engine,
                             character_data=payloads.CHARACTER_DATA.get(engine))
    await harness.chat(game_id, "__ARRIVEE__")
    await harness.drain()
    harness.llm.calls.clear()
    return game_id


@pytest.mark.parametrize("engine", ["narrative", "fate_core", "d6"])
async def test_c04_engine_turn_with_test(harness, engine, monkeypatch):
    game_id = await _engine_game(harness, engine)
    harness.llm._responses["mechanical"] = payloads.mechanical(
        requires_test=True, skill="Athlétisme", skill_value=2, difficulty=1)
    # Fate dice forced to +1 (success): a seed-dependent failure would pause on roll_pending.
    monkeypatch.setattr(fate_core, "random", SimpleNamespace(choice=lambda seq: 1))
    events = await harness.chat(game_id, "Je saute par-dessus la barrière.")
    await harness.drain()
    snap = harness.snapshot(events, await harness.db_summary(game_id))
    assert_snapshot(f"c04_engine_turn[{engine}]", snap)


async def test_c05_fate_invocation_pending_then_resume(harness, monkeypatch):
    game_id = await _engine_game(harness, "fate_core")
    harness.llm._responses["mechanical"] = payloads.mechanical(
        requires_test=True, skill="Athlétisme", skill_value=0, difficulty=4)
    # fate_core only uses random.choice for Fudge dice: force four -1 dice (failure).
    monkeypatch.setattr(fate_core, "random", SimpleNamespace(choice=lambda seq: -1))
    events = await harness.chat(game_id, "Je tente un saut impossible.")
    pending = [e for e in events if e["type"] == "roll_pending"]
    assert pending, harness.summarize(events)
    roll_id = pending[0]["roll_id"]
    aspect = pending[0]["aspects"][0]
    aspect_name = aspect["name"] if isinstance(aspect, dict) else aspect

    resumed = await harness.chat(game_id, "Je tente un saut impossible.",
                                 roll_id=roll_id, invoked_aspects=[aspect_name])
    await harness.drain()
    assert_snapshot("c05_fate_invocation", {
        "first": harness.summarize(events),
        "resume": harness.summarize(resumed),
        # Sorted: resolver and director run as concurrent tasks (see ChatHarness.snapshot).
        "llm_calls": sorted(harness.llm.purposes()),
        "db_counts": await harness.db_summary(game_id),
    })


async def test_c06_fate_compel_proposed(harness):
    game_id = await _engine_game(harness, "fate_core")
    harness.llm._responses["narration"] = payloads.NARRATION_WITH_COMPEL
    events = await harness.chat(game_id, "Je traverse le marché.")
    await harness.drain()
    done = [e for e in events if e["type"] == "done"]
    assert_snapshot("c06_fate_compel", {
        "sse": harness.summarize(events),
        "done_keys": sorted(done[0].keys()) if done else [],
        "db_counts": await harness.db_summary(game_id),
    })


@pytest.mark.xfail(strict=True, reason="#9: genre-specific arrival text never used")
async def test_c18_dark_fantasy_arrival_has_no_ai_companion_text(harness, monkeypatch):
    captured = {}
    original = llm_service.LLMService.stream_narration

    async def spy(self, system_prompt, messages, *args, **kwargs):
        captured["messages"] = messages
        return await original(self, system_prompt, messages, *args, **kwargs)

    monkeypatch.setattr(llm_service.LLMService, "stream_narration", spy)
    game_id = await harness.create_game("none")
    await harness.chat(game_id, "__INIT__", engine="none",
                       world_config={"genre": "dark_fantasy", "difficulty": "moderate"})
    await harness.drain()
    # Reach the first-light branch (api/routes.py: world_created and no current location);
    # the scripted world sets a start location at init, which would skip that branch.
    # The genre carries its own arrival text, as the preset genres do in production.
    async with harness.pool.acquire() as conn:
        await conn.execute("UPDATE games SET current_location_id = NULL WHERE id = $1", game_id)
        await conn.execute(
            "UPDATE genres SET arrival_prompt = $1 WHERE slug = 'dark_fantasy'",
            "Tu arrives a {world_name}, une lanterne a la main.")
    captured.clear()
    await harness.chat(game_id, "__ARRIVEE__")
    await harness.drain()
    assert captured.get("messages"), "spy captured no narration call"
    assert "IA personnelle" not in str(captured["messages"])
