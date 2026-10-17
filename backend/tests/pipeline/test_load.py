"""Load step: on a resume, the stored action is the turn's input from the start (#78)."""

import pytest

from pipeline import turn
from pipeline.steps import load
from tests.plugins.pending_roll import PENDING_ACTION


@pytest.fixture
def loaded(monkeypatch) -> list:
    """Every Prepared that load_turn returned during the test, in order."""
    prepared = []
    original = turn.load_turn

    async def spy(ctx):
        prepared.append(await original(ctx))
        return prepared[-1]

    monkeypatch.setattr(turn, "load_turn", spy)
    return prepared


async def test_resume_loads_the_stored_action(harness, pending, loaded):
    game_id, event = pending
    events = await harness.chat(game_id, "autre chose", roll_id=event["roll_id"],
                                invoked_aspects=[])
    await harness.drain()
    assert "done" in harness.summarize(events), events
    prepared = loaded[0]
    assert prepared.resumed_roll is not None
    assert str(prepared.resumed_roll.id) == event["roll_id"]
    assert prepared.player_input == PENDING_ACTION
    assert prepared.player_message == PENDING_ACTION
    assert prepared.context.player_input == PENDING_ACTION


async def test_arrival_without_genre_prompt_sends_the_default_message_and_saves_the_token(harness, loaded):
    game_id = await harness.create_game()
    await harness.init_world(game_id)
    events = await harness.chat(game_id, load.ARRIVAL_TOKEN)
    await harness.drain()
    assert "done" in harness.summarize(events), events
    prepared = loaded[0]
    assert prepared.is_arrival and prepared.resumed_roll is None
    assert prepared.player_message == load.ARRIVAL_TOKEN
    # The harness genre (sci_fi) has no arrival_prompt: the default message is sent.
    assert prepared.player_input == "Je viens d'arriver."
    assert prepared.context.player_input == prepared.player_input
