"""director_runs: the initial Director runs on the supervisor and is awaited, bounded (#79, #19)."""

import asyncio
from uuid import uuid4

from pipeline import director_runs
from workers import supervisor

TIMEOUT = 5.0


async def test_wait_for_initial_is_bounded_and_never_cancels_the_run():
    game_id, release = uuid4(), asyncio.Event()
    run = director_runs.start_initial(game_id, release.wait(), wait_limit=0.05)

    await asyncio.wait_for(director_runs.wait_for_initial(game_id), TIMEOUT)
    assert not run.done()  # limit reached: the turn goes on, the run keeps going
    assert run.get_name() == f"director_initial:{game_id}"
    release.set()
    await asyncio.wait({run}, timeout=TIMEOUT)


async def test_scheduled_wait_without_initial_returns_at_once():
    game_id, release = uuid4(), asyncio.Event()
    other = supervisor.enqueue(game_id, "post_turn", release.wait())

    await asyncio.wait_for(director_runs.wait_for_initial(game_id), 0.5)
    release.set()
    await asyncio.wait({other}, timeout=TIMEOUT)


async def test_cancelling_a_waiting_turn_leaves_the_run_alive():
    game_id, release = uuid4(), asyncio.Event()
    run = director_runs.start_initial(game_id, release.wait(), wait_limit=TIMEOUT)
    turn = asyncio.create_task(director_runs.wait_for_initial(game_id))
    await asyncio.sleep(0)  # the turn is now waiting

    turn.cancel()
    await asyncio.wait({turn}, timeout=TIMEOUT)

    assert turn.cancelled()
    assert not run.done() and supervisor.pending(game_id) == 1
    release.set()
    await asyncio.wait({run}, timeout=TIMEOUT)


async def test_finished_initial_is_forgotten():
    game_id = uuid4()
    run = director_runs.start_initial(game_id, asyncio.sleep(0), wait_limit=TIMEOUT)
    await asyncio.wait({run}, timeout=TIMEOUT)
    await asyncio.sleep(0)  # done callbacks run

    assert game_id not in director_runs._initial
    await asyncio.wait_for(director_runs.wait_for_initial(game_id), 0.5)
