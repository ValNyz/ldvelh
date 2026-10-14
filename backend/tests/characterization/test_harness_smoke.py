"""The harness itself must reach the app and record LLM calls."""


async def test_init_world_reaches_world_gen(harness):
    game_id = await harness.create_game("none")
    events = await harness.init_world(game_id)
    types = harness.summarize(events)
    assert "error" not in types, events
    purposes = harness.llm.purposes()
    assert "world_gen" in purposes
    # Proves the double served every call: nothing fell through to an unclassified/real provider.
    assert purposes and "unknown" not in purposes
    db = await harness.db_summary(game_id)
    assert db["locations"] > 0 and db["characters"] > 0
