"""Post-turn hooks: turn subscribers in order, new-cycle subscribers in one transaction (#95)."""

import logging
from uuid import uuid4

import pytest

from domain.turn import NarrationState, TurnCommitted
from repos import turns
from services import hooks, subscribers


def _event(game_id, message_id, *, previous_cycle=1, cycle=2) -> TurnCommitted:
    return TurnCommitted(game_id=game_id, previous_cycle=previous_cycle, cycle=cycle,
                         time="08h00", user_message_id=uuid4(), assistant_message_id=message_id,
                         turn_id=uuid4())


async def _game_with_message(pool, user):
    from services.game_service import GameService

    game_id = await GameService(pool).create_game(user["id"])
    async with pool.acquire() as conn:
        _, assistant_id = await turns.save_turn_messages(
            conn, game_id, user_message="Je pars.", assistant_message="Tu pars.",
            state=NarrationState(cycle=1, time="", location=None, npcs_present=[], date=None),
            narrator_deltas={}, engine_snapshot=None, turn_id=None)
    return game_id, assistant_id


async def test_turn_hooks_run_in_order_and_survive_a_failure(caplog):
    hooks.reset()
    calls = []

    @hooks.on_turn_committed
    async def first(pool, session, event):
        calls.append("first")

    @hooks.on_turn_committed
    async def second(pool, session, event):
        calls.append("second")
        raise RuntimeError("subscriber exploded")

    @hooks.on_turn_committed
    async def third(pool, session, event):
        calls.append("third")

    event = _event(uuid4(), uuid4())
    with caplog.at_level(logging.ERROR, logger="services.hooks"):
        await hooks.run_turn_committed(object(), object(), event)

    assert calls == ["first", "second", "third"]
    errors = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]
    assert any("second" in m and str(event.game_id) in m for m in errors), errors


@pytest.mark.integration
async def test_new_cycle_hooks_share_one_transaction(test_pool, test_user):
    game_id, message_id = await _game_with_message(test_pool, test_user)
    hooks.reset()

    @hooks.on_new_cycle
    async def insert_seed(conn, gid, cycle):
        await conn.execute("INSERT INTO narrative_seeds (game_id, cycle, text) VALUES ($1, $2, $3)",
                           gid, cycle, "graine")

    @hooks.on_new_cycle
    async def boom(conn, gid, cycle):
        raise RuntimeError("subscriber exploded")

    await hooks.run_new_cycle(test_pool, _event(game_id, message_id))

    async with test_pool.acquire() as conn:
        seeds = await conn.fetchval("SELECT count(*) FROM narrative_seeds WHERE game_id = $1",
                                    game_id)
    assert seeds == 0


@pytest.mark.integration
async def test_new_cycle_hooks_skip_a_rolled_back_turn(test_pool, test_user):
    game_id, _ = await _game_with_message(test_pool, test_user)
    hooks.reset()
    calls = []

    @hooks.on_new_cycle
    async def spy(conn, gid, cycle):
        calls.append(cycle)

    await hooks.run_new_cycle(test_pool, _event(game_id, uuid4()))

    assert calls == []


async def test_new_cycle_commit_failure_blames_the_commit(monkeypatch, caplog):
    from contextlib import asynccontextmanager

    class CommitFails:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            if exc_type is None:
                raise RuntimeError("commit failed")
            return False

    class FakeConn:
        def transaction(self):
            return CommitFails()

    class FakePool:
        @asynccontextmanager
        async def acquire(self):
            yield FakeConn()

    async def held(conn, message_id):
        return True

    monkeypatch.setattr(turns, "hold_source_message", held)
    hooks.reset()
    calls = []

    @hooks.on_new_cycle
    async def last_subscriber(conn, gid, cycle):
        calls.append(cycle)

    event = _event(uuid4(), uuid4())
    with caplog.at_level(logging.ERROR, logger="services.hooks"):
        await hooks.run_new_cycle(FakePool(), event)

    assert calls == [event.cycle]
    [error] = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]
    assert "new_cycle commit failed" in error and str(event.game_id) in error
    assert "last_subscriber" not in error


def test_register_defaults_wires_director_engine_and_seeds():
    from services import director_service

    hooks.reset()
    subscribers.register_defaults()
    subscribers.register_defaults()  # registered once each, even when called twice

    assert hooks._turn_hooks == [director_service.on_turn_committed]
    assert hooks._cycle_hooks == [subscribers.engine_new_cycle, subscribers.archive_seeds]


@pytest.mark.integration
async def test_archive_seeds_at_new_cycle(test_pool, test_user):
    game_id, message_id = await _game_with_message(test_pool, test_user)
    async with test_pool.acquire() as conn:
        for cycle in (1, 5):
            await conn.execute(
                "INSERT INTO narrative_seeds (game_id, cycle, text) VALUES ($1, $2, $3)",
                game_id, cycle, f"graine {cycle}")

    await hooks.run_new_cycle(test_pool, _event(game_id, message_id, previous_cycle=11, cycle=12))

    async with test_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT cycle, status FROM narrative_seeds WHERE game_id = $1 ORDER BY cycle", game_id)
    assert [(r["cycle"], r["status"]) for r in rows] == [(1, "archived"), (5, "active")]
