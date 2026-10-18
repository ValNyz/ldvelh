"""#86: a malformed narrator time or date never discards a paid turn."""

import json
import logging

from tests.characterization import payloads


async def _game_row(harness, game_id):
    async with harness.pool.acquire() as conn:
        return await conn.fetchrow(
            'SELECT "current_time" AS t, "current_date" AS d FROM games WHERE id = $1', game_id)


async def _last_message(harness, game_id):
    async with harness.pool.acquire() as conn:
        return await conn.fetchrow(
            """SELECT m.time, m.game_date FROM messages m
               JOIN conversations c ON c.id = m.conversation_id
               WHERE c.game_id = $1 ORDER BY m.created_at DESC, m.sequence DESC LIMIT 1""",
            game_id)


async def test_unusable_new_time_commits_the_turn_with_the_previous_time(
        harness, world_game, caplog):
    before = await _game_row(harness, world_game)
    narration = json.loads(payloads.NARRATION)
    narration["time"] = {"new_time": "vers 10h", "ellipse": False}
    harness.llm._responses["narration"] = json.dumps(narration, ensure_ascii=False)

    with caplog.at_level(logging.WARNING):
        events = await harness.chat(world_game, "J'attends un peu.")
        await harness.drain()

    assert "done" in harness.summarize(events)
    assert "error" not in harness.summarize(events)
    after = await _game_row(harness, world_game)
    assert after["t"] == before["t"]
    assert (await _last_message(harness, world_game))["time"] == before["t"]
    warnings = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("time" in w.lower() for w in warnings)
    assert not any("vers 10h" in w for w in warnings)


async def test_variant_new_time_is_stored_normalised(harness, world_game):
    narration = json.loads(payloads.NARRATION)
    narration["time"] = {"new_time": "9h5", "ellipse": False}
    harness.llm._responses["narration"] = json.dumps(narration, ensure_ascii=False)
    await harness.chat(world_game, "J'attends un peu.")
    await harness.drain()
    assert (await _game_row(harness, world_game))["t"] == "09h05"


async def test_overlong_new_date_commits_truncated(harness, world_game):
    narration = json.loads(payloads.NARRATION)
    narration["day_transition"] = {"new_date": "Mardi 19 Juillet 2847, " + "très tard " * 20}
    harness.llm._responses["narration"] = json.dumps(narration, ensure_ascii=False)
    events = await harness.chat(world_game, "Je dors.")
    await harness.drain()
    assert "error" not in harness.summarize(events)
    row = await _game_row(harness, world_game)
    assert row["d"].startswith("Mardi 19 Juillet 2847") and len(row["d"]) <= 50
    assert (await _last_message(harness, world_game))["game_date"] == row["d"]
