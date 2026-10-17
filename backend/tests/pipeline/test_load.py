"""Load step: on a resume, the stored action is the turn's input from the start (#78)."""

from pipeline import turn
from tests.test_pending_roll import ACTION, pending  # noqa: F401  (fixture)


async def test_resume_loads_the_stored_action(harness, pending, monkeypatch):  # noqa: F811
    game_id, event = pending
    prepared = []
    original = turn.load_turn

    async def spy(ctx):
        prepared.append(await original(ctx))
        return prepared[-1]

    monkeypatch.setattr(turn, "load_turn", spy)
    events = await harness.chat(game_id, "autre chose", roll_id=event["roll_id"],
                                invoked_aspects=[])
    await harness.drain()
    assert "done" in harness.summarize(events), events
    assert prepared[0].player_input == ACTION
    assert prepared[0].player_message == ACTION
    assert prepared[0].context.player_input == ACTION


async def test_plain_turn_keeps_the_protocol_token_to_save(harness, monkeypatch):
    game_id = await harness.create_game()
    await harness.init_world(game_id)
    prepared = []
    original = turn.load_turn

    async def spy(ctx):
        prepared.append(await original(ctx))
        return prepared[-1]

    monkeypatch.setattr(turn, "load_turn", spy)
    await harness.chat(game_id, "__ARRIVEE__")
    await harness.drain()
    assert prepared[0].is_arrival
    assert prepared[0].player_message == "__ARRIVEE__"
    assert prepared[0].player_input != "__ARRIVEE__"
