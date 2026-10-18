"""workers.game_locks: per-game turn lock with idle-entry purge (#94)."""

import asyncio
from uuid import uuid4

from workers import game_locks

TIMEOUT = 5.0


async def _settle():
    await asyncio.sleep(0.01)


async def test_hold_serializes_two_holders():
    game = uuid4()
    first_in, release_first, second_in = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def first():
        async with game_locks.hold(game):
            first_in.set()
            await release_first.wait()

    async def second():
        async with game_locks.hold(game):
            second_in.set()

    t1 = asyncio.create_task(first())
    await asyncio.wait_for(first_in.wait(), TIMEOUT)
    t2 = asyncio.create_task(second())
    await _settle()
    assert not second_in.is_set()
    release_first.set()
    await asyncio.wait_for(asyncio.gather(t1, t2), TIMEOUT)
    assert second_in.is_set()


async def test_entry_is_purged_when_nobody_waits():
    game = uuid4()
    async with game_locks.hold(game):
        assert game_locks.tracked() == 1
        assert game_locks.is_held(game) is True
    assert game_locks.tracked() == 0
    assert game_locks.is_held(game) is False


async def test_entry_survives_while_a_waiter_is_queued():
    game = uuid4()
    release_first, second_in, release_second = asyncio.Event(), asyncio.Event(), asyncio.Event()
    first_in = asyncio.Event()

    async def first():
        async with game_locks.hold(game):
            first_in.set()
            await release_first.wait()

    async def second():
        async with game_locks.hold(game):
            second_in.set()
            await release_second.wait()

    t1 = asyncio.create_task(first())
    await asyncio.wait_for(first_in.wait(), TIMEOUT)
    t2 = asyncio.create_task(second())
    await _settle()
    release_first.set()
    await asyncio.wait_for(second_in.wait(), TIMEOUT)
    assert game_locks.tracked() == 1
    assert game_locks.is_held(game) is True
    release_second.set()
    await asyncio.wait_for(asyncio.gather(t1, t2), TIMEOUT)
    assert game_locks.tracked() == 0


async def test_cancelled_waiter_does_not_leak_an_entry():
    game = uuid4()
    release, first_in = asyncio.Event(), asyncio.Event()

    async def first():
        async with game_locks.hold(game):
            first_in.set()
            await release.wait()

    async def waiter():
        async with game_locks.hold(game):
            pass

    t1 = asyncio.create_task(first())
    await asyncio.wait_for(first_in.wait(), TIMEOUT)
    t2 = asyncio.create_task(waiter())
    await _settle()
    t2.cancel()
    await asyncio.gather(t2, return_exceptions=True)
    release.set()
    await asyncio.wait_for(t1, TIMEOUT)
    assert game_locks.tracked() == 0
