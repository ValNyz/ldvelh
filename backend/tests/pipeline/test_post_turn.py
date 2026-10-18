"""Post-turn jobs of one game run one after the other, none is skipped (#17)."""

import asyncio
from uuid import uuid4

from domain.turn import TurnCommitted
from pipeline import post_turn
from workers import supervisor

TIMEOUT = 5.0


def _event(game_id, cycle: int) -> TurnCommitted:
    return TurnCommitted(game_id=game_id, previous_cycle=cycle, cycle=cycle, time="08h00",
                         user_message_id=uuid4(), assistant_message_id=uuid4())


def test_new_cycle_is_true_only_when_the_cycle_grows():
    game_id = uuid4()
    assert _event(game_id, 1).new_cycle is False
    later = TurnCommitted(game_id=game_id, previous_cycle=1, cycle=2, time="08h00",
                          user_message_id=uuid4(), assistant_message_id=uuid4())
    assert later.new_cycle is True


async def test_two_post_turn_jobs_run_in_order_and_both_extract(monkeypatch):
    game_id, started, release = uuid4(), asyncio.Event(), asyncio.Event()
    calls, results = [], []

    async def recorder(pool, game_id, *, trigger_cycle, triggers, session,
                       assistant_message_id, message_content, narrator_deltas):
        calls.append(assistant_message_id)
        if len(calls) == 1:
            started.set()
            await release.wait()  # the first extraction is still running at the second enqueue
        result = {"resolver": None, "extractors": {}}
        results.append(result)
        return result

    monkeypatch.setattr(post_turn, "run_resolve_and_extract", recorder)
    first, second = _event(game_id, 1), _event(game_id, 1)
    pool, session = object(), object()

    for event in (first, second):
        supervisor.enqueue(game_id, "post_turn", post_turn.run_post_turn(
            pool, session, event, triggers=["characters"], message_content="texte",
            narrator_deltas={}))
    await asyncio.wait_for(started.wait(), TIMEOUT)
    assert calls == [first.assistant_message_id]
    assert supervisor.pending(game_id) == 2  # the second waits, it is not dropped
    release.set()
    await supervisor.wait_idle(game_id, timeout=TIMEOUT)

    assert calls == [first.assistant_message_id, second.assistant_message_id]
    # Both jobs ran to completion; the real orchestrator skip path is covered by C-17.
    assert len(results) == 2


async def test_run_post_turn_forwards_the_turn(monkeypatch):
    seen = {}

    async def recorder(pool, game_id, **kwargs):
        seen.update(pool=pool, game_id=game_id, **kwargs)

    monkeypatch.setattr(post_turn, "run_resolve_and_extract", recorder)
    event = TurnCommitted(game_id=uuid4(), previous_cycle=1, cycle=2, time="09h00",
                          user_message_id=uuid4(), assistant_message_id=uuid4())
    pool, session = object(), object()

    await post_turn.run_post_turn(pool, session, event, triggers=None, message_content="texte",
                                  narrator_deltas={"a": 1})

    assert seen == {"pool": pool, "game_id": event.game_id, "trigger_cycle": 2,
                    "triggers": None, "session": session,
                    "assistant_message_id": event.assistant_message_id,
                    "message_content": "texte", "narrator_deltas": {"a": 1}}
