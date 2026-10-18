"""schedule_background queues the post-turn job on the game's supervisor queue (#17)."""

import asyncio
from types import SimpleNamespace
from uuid import uuid4

from domain.game import GameSnapshot
from domain.turn import NarrationState, TurnCommitted
from pipeline.context import TurnContext, TurnRequest
from pipeline.steps import schedule
from pipeline.steps.commit import Committed
from pipeline.steps.narrate import Narrated
from workers import supervisor

TIMEOUT = 5.0


def _ctx() -> TurnContext:
    game_id = uuid4()
    snapshot = GameSnapshot(id=game_id, world_created=True, current_cycle=1,
                            current_time="08h00", current_location_name="Bar")
    return TurnContext(request=TurnRequest(game_id=game_id, user_id=uuid4(), message="Je regarde."),
                       snapshot=snapshot, session=object(), sink=None, pool=object(),
                       engine=None, ref="test")


async def test_schedule_enqueues_one_post_turn_job(monkeypatch):
    calls = []

    async def spy_post_turn(pool, session, event, **kwargs):
        calls.append((event, kwargs))

    async def no_director(ctx, committed):
        return None

    monkeypatch.setattr(schedule, "run_post_turn", spy_post_turn)
    monkeypatch.setattr(schedule, "_schedule_director", no_director)
    ctx = _ctx()
    game_id = ctx.request.game_id
    narrated = Narrated(narration=SimpleNamespace(extraction_triggers=["characters"]),
                        display_text="Le bar est calme.", cost=None)
    committed = Committed(state=NarrationState(cycle=2, time="08h30", location="Bar",
                                               npcs_present=[], date=None),
                          user_message_id=uuid4(), assistant_message_id=uuid4(),
                          narrator_deltas={"entity_reveals": []})

    await schedule.schedule_background(ctx, narrated, committed)

    assert supervisor.pending(game_id) == 1
    names = [task.get_name() for task in asyncio.all_tasks()]
    assert f"post_turn:{game_id}" in names
    await supervisor.wait_idle(game_id, timeout=TIMEOUT)
    [(event, kwargs)] = calls
    assert isinstance(event, TurnCommitted)
    assert event.game_id == game_id
    assert event.cycle == committed.state.cycle
    assert event.previous_cycle == ctx.snapshot.current_cycle
    assert event.new_cycle is True
    assert event.time == committed.state.time
    assert event.assistant_message_id == committed.assistant_message_id
    assert event.user_message_id == committed.user_message_id
    assert kwargs["triggers"] == (narrated.narration.extraction_triggers or None)
    assert kwargs["message_content"] == narrated.display_text
    assert kwargs["narrator_deltas"] == committed.narrator_deltas


async def test_schedule_passes_none_when_no_trigger(monkeypatch):
    calls = []

    async def spy_post_turn(pool, session, event, **kwargs):
        calls.append(kwargs["triggers"])

    async def no_director(ctx, committed):
        return None

    monkeypatch.setattr(schedule, "run_post_turn", spy_post_turn)
    monkeypatch.setattr(schedule, "_schedule_director", no_director)
    ctx = _ctx()
    narrated = Narrated(narration=SimpleNamespace(extraction_triggers=[]),
                        display_text="Rien.", cost=None)
    committed = Committed(state=NarrationState(cycle=1, time="08h10", location="Bar",
                                               npcs_present=[], date=None),
                          user_message_id=uuid4(), assistant_message_id=uuid4(),
                          narrator_deltas={})

    await schedule.schedule_background(ctx, narrated, committed)
    await supervisor.wait_idle(ctx.request.game_id, timeout=TIMEOUT)

    assert calls == [None]
