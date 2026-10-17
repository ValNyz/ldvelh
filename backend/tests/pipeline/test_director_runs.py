"""director_runs: one Director per game in flight; the initial one awaited, bounded (#79)."""

import asyncio
from uuid import uuid4

from pipeline import director_runs

TIMEOUT = 5.0


async def test_second_start_is_dropped_while_one_runs():
    game_id, release = uuid4(), asyncio.Event()
    first = director_runs.start(game_id, release.wait())
    second_coro = asyncio.sleep(0)

    assert director_runs.start(game_id, second_coro) is None
    assert director_runs.is_running(game_id)
    release.set()
    await asyncio.wait({first}, timeout=TIMEOUT)
    assert not director_runs.is_running(game_id)


async def test_wait_for_initial_is_bounded_and_never_cancels_the_run():
    game_id, release = uuid4(), asyncio.Event()
    run = director_runs.start(game_id, release.wait(), wait_limit=0.05)

    await asyncio.wait_for(director_runs.wait_for_initial(game_id), TIMEOUT)
    assert not run.done()  # limit reached: the turn goes on, the run keeps going
    release.set()
    await asyncio.wait({run}, timeout=TIMEOUT)


async def test_scheduled_run_is_not_awaited():
    game_id, release = uuid4(), asyncio.Event()
    run = director_runs.start(game_id, release.wait())

    await asyncio.wait_for(director_runs.wait_for_initial(game_id), 0.5)
    release.set()
    await asyncio.wait({run}, timeout=TIMEOUT)


async def test_cancelling_a_waiting_turn_leaves_the_run_alive():
    game_id, release = uuid4(), asyncio.Event()
    run = director_runs.start(game_id, release.wait(), wait_limit=TIMEOUT)
    turn = asyncio.create_task(director_runs.wait_for_initial(game_id))
    await asyncio.sleep(0)  # the turn is now waiting

    turn.cancel()
    await asyncio.wait({turn}, timeout=TIMEOUT)

    assert turn.cancelled()
    assert not run.done() and director_runs.is_running(game_id)
    release.set()
    await asyncio.wait({run}, timeout=TIMEOUT)


async def test_failed_run_is_forgotten():
    game_id = uuid4()

    async def boom():
        raise RuntimeError("director exploded")

    run = director_runs.start(game_id, boom())
    await asyncio.wait({run}, timeout=TIMEOUT)

    assert isinstance(run.exception(), RuntimeError)
    assert not director_runs.is_running(game_id)


async def test_cancelled_run_is_forgotten():
    game_id = uuid4()
    run = director_runs.start(game_id, asyncio.Event().wait())

    run.cancel()
    await asyncio.wait({run}, timeout=TIMEOUT)

    assert run.cancelled()
    assert not director_runs.is_running(game_id)
