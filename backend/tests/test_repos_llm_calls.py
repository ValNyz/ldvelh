"""LLM call log (repos.llm_calls): one row per billed call, the account summary read from it
(#106)."""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

import asyncpg
import pytest

from llm.call_log import CallLog
from llm.session import LLMSession, Purpose
from repos import llm_calls, turns
from services.game_service import GameService
from services.llm_providers import LLMUsage
from tests.test_llm_session import FakeProvider

pytestmark = pytest.mark.integration


def _usage(inp: int, out: int, cache_write: int = 0, cache_read: int = 0) -> dict:
    return {
        "input_tokens": inp,
        "output_tokens": out,
        "cache_creation_input_tokens": cache_write,
        "cache_read_input_tokens": cache_read,
    }


def _row(
    user_id, game_id, purpose, model, usage, cost, *, provider="mistral", turn_id=None
):
    return {
        "turn_id": turn_id,
        "game_id": game_id,
        "user_id": user_id,
        "purpose": purpose,
        "provider": provider,
        "model": model,
        "usage": usage,
        "cost_usd": cost,
        "cost_unknown": False,
        "created_at": datetime.now(UTC),
    }


async def _insert(conn, user_id, game_id, purpose, model, usage, cost):
    await llm_calls.insert_calls(
        conn, [_row(user_id, game_id, purpose, model, usage, cost)]
    )


async def test_user_summary_groups_by_purpose_and_model(test_pool, test_user):
    user_id = test_user["id"]
    game_id = await GameService(test_pool).create_game(user_id)
    async with test_pool.acquire() as conn:
        await _insert(
            conn,
            user_id,
            game_id,
            "narration",
            "m-large",
            _usage(1000, 100, 10, 20),
            0.0016,
        )
        await _insert(
            conn, user_id, game_id, "narration", "m-large", _usage(500, 50), 0.0008
        )
        await _insert(
            conn, user_id, game_id, "narration", "m-small", _usage(200, 20), 0.0001
        )
        await _insert(
            conn, user_id, None, "extraction", "m-small", _usage(300, 30), 0.000123
        )
        summary = await llm_calls.user_summary(conn, user_id)

    assert summary == {
        "purposes": {
            "narration": {
                "models": {
                    "m-large": {
                        "input_tokens": 1500,
                        "output_tokens": 150,
                        "cache_creation_input_tokens": 10,
                        "cache_read_input_tokens": 20,
                        "calls": 2,
                        "cost_usd": 0.0024,
                    },
                    "m-small": {
                        "input_tokens": 200,
                        "output_tokens": 20,
                        "cache_creation_input_tokens": 0,
                        "cache_read_input_tokens": 0,
                        "calls": 1,
                        "cost_usd": 0.0001,
                    },
                },
                "cost_usd": 0.0025,
                "calls": 3,
            },
            "extraction": {
                "models": {
                    "m-small": {
                        "input_tokens": 300,
                        "output_tokens": 30,
                        "cache_creation_input_tokens": 0,
                        "cache_read_input_tokens": 0,
                        "calls": 1,
                        "cost_usd": 0.000123,
                    },
                },
                "cost_usd": 0.000123,
                "calls": 1,
            },
        },
        "total_cost_usd": 0.002623,
    }
    assert all(
        isinstance(v, float)
        for v in (
            summary["total_cost_usd"],
            summary["purposes"]["narration"]["cost_usd"],
            summary["purposes"]["narration"]["models"]["m-large"]["cost_usd"],
        )
    )


async def test_user_summary_filters_by_user(test_pool, test_user, second_user):
    async with test_pool.acquire() as conn:
        await _insert(conn, test_user["id"], None, "narration", "m", _usage(1, 1), 2.0)
        await _insert(conn, second_user["id"], None, "director", "m", _usage(1, 1), 6.0)
        mine = await llm_calls.user_summary(conn, test_user["id"])
        other = await llm_calls.user_summary(conn, second_user["id"])

    assert (mine["total_cost_usd"], list(mine["purposes"])) == (2.0, ["narration"])
    assert (other["total_cost_usd"], list(other["purposes"])) == (6.0, ["director"])


async def test_summary_uses_each_call_provider(test_pool, test_user, monkeypatch):
    # The same model id priced differently on two providers: each call keeps its own cost.
    from llm.usage import call_cost
    from services import pricing

    for provider, rate in (("nebius", 1.0), ("wandb", 3.0)):
        monkeypatch.setitem(
            pricing._DYNAMIC_PRICING,
            f"{provider}/qwen",
            pricing.ModelPricing(input=rate, output=rate),
        )
    usage = LLMUsage(input_tokens=1_000_000)
    rows = [
        _row(
            test_user["id"],
            None,
            "narration",
            "qwen",
            _usage(1_000_000, 0),
            call_cost(usage, provider, "qwen"),
            provider=provider,
        )
        for provider in ("nebius", "wandb")
    ]
    async with test_pool.acquire() as conn:
        await llm_calls.insert_calls(conn, rows)  # one insert for both rows
        summary = await llm_calls.user_summary(conn, test_user["id"])
    assert summary["total_cost_usd"] == 4.0
    assert summary["purposes"]["narration"]["calls"] == 2


async def test_user_summary_of_a_user_without_calls_is_empty(test_pool, test_user):
    async with test_pool.acquire() as conn:
        assert await llm_calls.user_summary(conn, test_user["id"]) == {
            "purposes": {},
            "total_cost_usd": 0.0,
        }


async def test_insert_marks_unpriced_models(test_pool, test_user):
    game_id = await GameService(test_pool).create_game(test_user["id"])
    # A session of the game, logging to the pool: "fake-main" has no price.
    session = LLMSession.from_provider(FakeProvider(usage=LLMUsage(10, 5)))
    session.calls = CallLog(test_pool, game_id=game_id, user_id=test_user["id"])
    call = await session.complete_json(Purpose.MECHANICAL, "sys", "user", 0.2, 100)
    await session.flush_calls()

    async with test_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM llm_calls WHERE game_id = $1", game_id)
    assert call.cost["cost_usd"] == 0
    assert row["cost_unknown"] is True and row["cost_usd"] == 0
    assert (row["purpose"], row["provider"], row["model"]) == (
        "mechanical",
        "fake",
        "fake-main",
    )
    assert row["user_id"] == test_user["id"] and row["turn_id"] is None
    assert row["usage"]["input_tokens"] == 10 and row["usage"]["output_tokens"] == 5


async def test_a_row_of_a_deleted_turn_is_stored_without_turn(test_pool, test_user):
    # A rollback may delete the turn before its job flushes: the paid call is kept, as the
    # turn FK's ON DELETE SET NULL would have kept it.
    user_id = test_user["id"]
    game_id = await GameService(test_pool).create_game(user_id)
    async with test_pool.acquire() as conn:
        kept = await turns.open_turn(conn, game_id)
        gone = await turns.open_turn(conn, game_id)
        await conn.execute("DELETE FROM turns WHERE id = $1", gone)
        await llm_calls.insert_calls(
            conn,
            [
                _row(
                    user_id, game_id, "narration", "m", _usage(1, 1), 0.1, turn_id=kept
                ),
                _row(
                    user_id, game_id, "resolver", "m", _usage(1, 1), 0.1, turn_id=gone
                ),
            ],
        )
        rows = await conn.fetch(
            "SELECT purpose, turn_id FROM llm_calls WHERE game_id = $1 ORDER BY id",
            game_id,
        )
    assert [(r["purpose"], r["turn_id"]) for r in rows] == [
        ("narration", kept),
        ("resolver", None),
    ]


async def test_insert_of_no_rows_is_a_no_op(test_pool):
    async with test_pool.acquire() as conn:
        await llm_calls.insert_calls(conn, [])
        assert await conn.fetchval("SELECT count(*) FROM llm_calls") == 0


async def test_a_deleted_game_keeps_its_calls_in_the_account_total(
    test_pool, test_user
):
    user_id = test_user["id"]
    game_id = await GameService(test_pool).create_game(user_id)
    async with test_pool.acquire() as conn:
        await _insert(conn, user_id, game_id, "narration", "m", _usage(1, 1), 0.25)
        await conn.execute("DELETE FROM games WHERE id = $1", game_id)
        summary = await llm_calls.user_summary(conn, user_id)
        stored = await conn.fetchval(
            "SELECT game_id FROM llm_calls WHERE user_id = $1", user_id
        )
    assert (
        summary["total_cost_usd"] == 0.25
        and summary["purposes"]["narration"]["calls"] == 1
    )
    assert stored is None  # ON DELETE SET NULL


async def test_a_flush_after_the_game_is_deleted_stores_no_game(test_pool, test_user):
    # A job of a game deleted meanwhile still logs its paid calls, without the game.
    user_id = test_user["id"]
    game_id = await GameService(test_pool).create_game(user_id)
    log = CallLog(test_pool, game_id=game_id, user_id=user_id)
    log.add(
        purpose="director",
        provider="fake",
        model="m",
        usage=_usage(1, 1),
        cost_usd=0.5,
        cost_unknown=False,
    )
    async with test_pool.acquire() as conn:
        await conn.execute("DELETE FROM games WHERE id = $1", game_id)
    await log.flush()
    async with test_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT game_id, purpose FROM llm_calls WHERE user_id = $1", user_id
        )
        summary = await llm_calls.user_summary(conn, user_id)
    assert [(r["game_id"], r["purpose"]) for r in rows] == [(None, "director")]
    assert summary["total_cost_usd"] == 0.5


async def test_rows_keep_the_time_of_their_call(test_pool, test_user):
    user_id = test_user["id"]
    called = datetime.now(UTC) - timedelta(minutes=5)
    row = {
        **_row(user_id, None, "narration", "m", _usage(1, 1), 0.1),
        "created_at": called,
    }
    async with test_pool.acquire() as conn:
        await llm_calls.insert_calls(conn, [row])
        stored = await conn.fetchval(
            "SELECT created_at FROM llm_calls WHERE user_id = $1", user_id
        )
    assert stored == called


async def test_a_turn_deleted_during_the_flush_is_retried_without_it(
    test_pool, test_user, monkeypatch, caplog
):
    # The turn goes away while the insert runs (FK error): the batch is retried once and
    # kept, with no turn.
    user_id = test_user["id"]
    game_id = await GameService(test_pool).create_game(user_id)
    async with test_pool.acquire() as conn:
        turn_id = await turns.open_turn(conn, game_id)
    log = CallLog(test_pool, game_id=game_id, user_id=user_id, turn_id=turn_id)
    log.add(
        purpose="resolver",
        provider="fake",
        model="m",
        usage=_usage(1, 1),
        cost_usd=0.5,
        cost_unknown=False,
    )
    real_insert, attempts = llm_calls.insert_calls, []

    async def racing_insert(conn, rows):
        attempts.append(len(rows))
        if len(attempts) == 1:
            async with test_pool.acquire() as other:
                await other.execute("DELETE FROM turns WHERE id = $1", turn_id)
            raise asyncpg.ForeignKeyViolationError("turn deleted meanwhile")
        await real_insert(conn, rows)

    monkeypatch.setattr(llm_calls, "insert_calls", racing_insert)
    with caplog.at_level(logging.ERROR, logger="llm.call_log"):
        await log.flush()
    async with test_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT turn_id, game_id, purpose FROM llm_calls WHERE user_id = $1",
            user_id,
        )
    assert attempts == [1, 1]
    assert [(r["turn_id"], r["game_id"], r["purpose"]) for r in rows] == [
        (None, game_id, "resolver")
    ]
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


async def test_a_cancelled_flush_logs_the_dropped_rows_and_reraises(
    test_pool, test_user, monkeypatch, caplog
):
    # CancelledError is a BaseException: the rows are gone, the loss must still be logged.
    user_id = test_user["id"]
    game_id = await GameService(test_pool).create_game(user_id)
    log = CallLog(test_pool, game_id=game_id, user_id=user_id)
    for _ in range(2):
        log.add(
            purpose="resolver",
            provider="fake",
            model="m",
            usage=_usage(1, 1),
            cost_usd=0.5,
            cost_unknown=False,
        )

    async def cancelled(conn, rows):
        raise asyncio.CancelledError

    monkeypatch.setattr(llm_calls, "insert_calls", cancelled)
    with (
        caplog.at_level(logging.ERROR, logger="llm.call_log"),
        pytest.raises(asyncio.CancelledError),
    ):
        await log.flush()
    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(errors) == 1
    assert "rows=2" in errors[0].getMessage()
    assert log.pending == 0
