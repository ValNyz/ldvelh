"""
Extractor write isolation (#24): each item is written in its own SAVEPOINT, a failed
item never takes the others down, and run() reports what was really committed.
"""

import logging
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from tests.helpers import character_names, extractor_for


def _fact(key):
    return {"fact_type": "observation", "description": "Une porte grince.",
            "semantic_key": key}


async def _fact_keys(test_pool, game_id):
    async with test_pool.acquire() as conn:
        rows = await conn.fetch("SELECT semantic_key FROM facts WHERE game_id = $1", game_id)
    return {r["semantic_key"] for r in rows}


async def test_unique_violation_in_one_item_keeps_the_other_items(test_pool, test_user):
    raw = {
        "entities_created": [{"name": "Alpha"}, {"name": "Beta"}],
        "entities_updated": [{"entity_ref": "Alpha", "changes": {"mood": "inquiet"}},
                             {"entity_ref": "Beta", "changes": {"mood": "calme"}}],
        "facts": [_fact("porte:grince:nuit")],
    }
    extractor, game_id = await extractor_for(test_pool, test_user, raw)
    real_update = extractor.populator.update_entity

    async def colliding_update(conn, entity_type, name, changes):
        if name == "Alpha":  # rename collision: server-side unique violation
            # (the name is derived from true_name, #152: the collision goes through it)
            await conn.execute("UPDATE characters SET true_name = 'Beta' "
                               "WHERE game_id = $1 AND name = 'Alpha'", game_id)
        return await real_update(conn, entity_type, name, changes)

    extractor.populator.update_entity = colliding_update
    result = await extractor.run("texte", {}, 1)

    assert await character_names(test_pool, game_id) >= {"Alpha", "Beta"}
    assert "porte:grince:nuit" in await _fact_keys(test_pool, game_id)
    async with test_pool.acquire() as conn:
        beta_mood = await conn.fetchval(
            "SELECT mood FROM characters WHERE game_id = $1 AND name = 'Beta'", game_id)
        logged = await conn.fetchval(
            "SELECT errors FROM extraction_logs WHERE game_id = $1", game_id)
    assert beta_mood == "calme"

    stats = result["stats"]
    assert (stats["entities_created"], stats["entities_updated"], stats["facts_created"]) \
        == (2, 1, 1)
    assert len(stats["errors"]) == 1 and stats["errors"][0].startswith("update:")
    assert result["success"] is False and result["partial"] is True
    assert result["cost"] == {"cost_usd": 0.001}
    assert logged == stats["errors"]


async def test_clean_run_reports_success(test_pool, test_user):
    extractor, game_id = await extractor_for(
        test_pool, test_user, {"entities_created": [{"name": "Gamma"}]})
    result = await extractor.run("texte", {}, 1)
    assert result["success"] is True and not result.get("partial")
    assert result["stats"]["errors"] == []
    assert "Gamma" in await character_names(test_pool, game_id)


async def test_populate_raising_returns_failure(test_pool, test_user):
    extractor, game_id = await extractor_for(
        test_pool, test_user, {"entities_created": [{"name": "Delta"}]})
    real_populate = extractor._populate

    async def failing_populate(conn, raw_result, cycle):
        await real_populate(conn, raw_result, cycle)
        raise RuntimeError("db hiccup")

    extractor._populate = failing_populate
    result = await extractor.run("texte", {}, 1)

    assert result["success"] is False and not result.get("partial")
    assert result["cost"] == {"cost_usd": 0.001}
    assert "Delta" not in await character_names(test_pool, game_id)  # rolled back
    async with test_pool.acquire() as conn:
        logged = await conn.fetchval(
            "SELECT errors FROM extraction_logs WHERE game_id = $1", game_id)
    assert logged and "db hiccup" in logged[0]


async def test_sql_error_swallowed_inside_an_item_fails_only_that_item(test_pool, test_user):
    """The aborted savepoint is rolled back: the item fails, the others commit."""
    extractor, game_id = await extractor_for(
        test_pool, test_user,
        {"entities_created": [{"name": "Epsilon"}],
         "entities_updated": [{"entity_ref": "Epsilon", "changes": {"mood": "las"}}]})

    async def swallowing_update(conn, _entity_type, _name, _changes):
        try:
            await conn.execute("SELECT 1/0")
        except Exception:
            pass
        return True

    extractor.populator.update_entity = swallowing_update
    result = await extractor.run("texte", {}, 1)

    assert result["success"] is False and result["partial"] is True
    assert "Epsilon" in await character_names(test_pool, game_id)
    [error] = result["stats"]["errors"]
    assert error.startswith("update:")
    async with test_pool.acquire() as conn:
        logged = await conn.fetchval(
            "SELECT errors FROM extraction_logs WHERE game_id = $1", game_id)
    assert logged == [error]


async def test_transaction_aborted_outside_any_savepoint_propagates(test_pool):
    """Nothing can commit any more: write_item must not hide it behind an item error."""
    import asyncpg
    import pytest

    from kg.item_writes import write_item

    async with test_pool.acquire() as conn:
        outer = conn.transaction()
        await outer.start()
        try:
            with pytest.raises(asyncpg.DivisionByZeroError):
                await conn.execute("SELECT 1/0")  # swallowed by the caller, outside a savepoint
            errors: list[str] = []
            with pytest.raises(asyncpg.InFailedSQLTransactionError):
                await write_item(conn, errors, "item", lambda: conn.execute("SELECT 1"))
            assert errors == []
        finally:
            await outer.rollback()


async def test_empty_response_keeps_the_billed_cost(test_pool, test_user):
    extractor, _ = await extractor_for(test_pool, test_user, {})
    result = await extractor.run("texte", {}, 1)
    assert result["success"] is False and result["error"] == "empty_response"
    assert result["cost"] == {"cost_usd": 0.001}


async def test_orchestrator_log_counts_real_outcomes(caplog):
    from services.extraction.orchestrator import (
        EXTRACTOR_MAP,
        run_resolve_and_extract,
    )

    outcomes = {
        "characters": {"success": True, "stats": {"errors": []}},
        "locations": {"success": False, "partial": True, "stats": {"errors": ["fact: x"]}},
        "organizations": {"success": False, "error": "populate_failed"},
        "progression": {"type": "progression", "skipped": True},
    }

    def _cls(outcome):
        inst = MagicMock()
        inst.run = AsyncMock(return_value=outcome)
        return MagicMock(return_value=inst)

    pool = MagicMock()
    with patch.dict(EXTRACTOR_MAP, {k: _cls(v) for k, v in outcomes.items()}), \
            caplog.at_level(logging.INFO, logger="services.extraction.orchestrator"):
        await run_resolve_and_extract(pool, uuid4(), trigger_cycle=1,
                                      triggers=list(outcomes), session=MagicMock(),
                                      message_content="texte")

    complete = [r.getMessage() for r in caplog.records if "Complete:" in r.getMessage()]
    assert len(complete) == 1
    assert "1 succeeded, 1 partial, 1 failed, 1 skipped (4 extractors)" in complete[0]


async def test_populate_skips_when_the_source_message_is_gone(test_pool, test_user):
    """#23: the source message was rolled back: nothing is written, the run is skipped."""
    extractor, game_id = await extractor_for(
        test_pool, test_user, {"entities_created": [{"name": "Zeta"}]})
    result = await extractor.run("texte", {}, 1, source_message_id=uuid4(), turn_id=uuid4())

    assert result["success"] is False and result["skipped"] is True
    assert result["error"] == "source_message_gone"
    assert result["cost"] == {"cost_usd": 0.001}
    assert "Zeta" not in await character_names(test_pool, game_id)
    async with test_pool.acquire() as conn:
        logs = await conn.fetchval(
            "SELECT COUNT(*) FROM extraction_logs WHERE game_id = $1", game_id)
    assert logs == 0


async def test_cancel_inside_the_guarded_transaction_releases_the_message(test_pool, test_user):
    """#23: a job cancelled after hold_source_message, before commit, rolls back: the
    rollback's DELETE of the message does not wait, and nothing was written."""
    import asyncio

    from domain.turn import NarrationState
    from repos import turns

    extractor, game_id = await extractor_for(
        test_pool, test_user, {"entities_created": [{"name": "Eta"}]})
    async with test_pool.acquire() as conn:
        _, message_id = await turns.save_turn_messages(
            conn, game_id, user_message="Je pars.", assistant_message="Tu pars.",
            state=NarrationState(cycle=1, time="", location=None, npcs_present=[], date=None),
            narrator_deltas={}, engine_snapshot=None, turn_id=None)
    real_populate = extractor._populate
    inside = asyncio.Event()

    async def blocking_populate(conn, raw_result, cycle):
        await real_populate(conn, raw_result, cycle)  # written, not committed
        inside.set()
        await asyncio.Event().wait()

    extractor._populate = blocking_populate
    job = asyncio.create_task(extractor.run("texte", {}, 1, source_message_id=message_id))
    await asyncio.wait_for(inside.wait(), 5)
    job.cancel()
    await asyncio.gather(job, return_exceptions=True)
    assert job.cancelled()

    async with test_pool.acquire() as conn:
        deleted = await asyncio.wait_for(
            conn.execute("DELETE FROM messages WHERE id = $1", message_id), 1.0)
    assert deleted == "DELETE 1"
    assert "Eta" not in await character_names(test_pool, game_id)


async def test_extraction_log_of_a_turn_rolled_back_meanwhile_is_dropped(
    test_pool, test_user, caplog
):
    """#105: the turn is deleted between the populate commit and the audit insert: the
    log row would reference a missing turn, so it is dropped with an INFO, no WARNING."""
    from repos import turns

    extractor, game_id = await extractor_for(
        test_pool, test_user, {"entities_created": [{"name": "Iota"}]})
    async with test_pool.acquire() as conn:
        turn_id = await turns.open_turn(conn, game_id)
    real_log = extractor.populator.log_extraction

    async def log_after_rollback(conn, cycle, stats, turn_id=None):
        async with test_pool.acquire() as other:
            await other.execute("DELETE FROM turns WHERE id = $1", turn_id)
        return await real_log(conn, cycle, stats, turn_id)

    extractor.populator.log_extraction = log_after_rollback
    with caplog.at_level(logging.INFO, logger="services.extraction.base"):
        result = await extractor.run("texte", {}, 1, turn_id=turn_id)

    assert result["success"] is True
    assert any("Turn rolled back, extraction log dropped" in r.getMessage()
               for r in caplog.records)
    assert not any(r.levelno >= logging.WARNING for r in caplog.records)
    async with test_pool.acquire() as conn:
        assert await conn.fetchval(
            "SELECT count(*) FROM extraction_logs WHERE game_id = $1", game_id) == 0


async def test_extraction_log_of_a_deleted_game_still_warns(test_pool, test_user, caplog):
    """#105: only the turn foreign key means "turn rolled back"; the game's (checked
    first) failing is a real error and keeps the WARNING."""
    from repos import turns

    extractor, game_id = await extractor_for(
        test_pool, test_user, {"entities_created": [{"name": "Kappa"}]})
    async with test_pool.acquire() as conn:
        turn_id = await turns.open_turn(conn, game_id)
    real_log = extractor.populator.log_extraction

    async def log_after_game_deleted(conn, cycle, stats, turn_id=None):
        async with test_pool.acquire() as other:
            await other.execute("DELETE FROM games WHERE id = $1", game_id)
        return await real_log(conn, cycle, stats, turn_id)

    extractor.populator.log_extraction = log_after_game_deleted
    with caplog.at_level(logging.INFO, logger="services.extraction.base"):
        await extractor.run("texte", {}, 1, turn_id=turn_id)

    messages = [r.getMessage() for r in caplog.records]
    assert not any("extraction log dropped" in m for m in messages)
    assert any("Log failed" in r.getMessage() and "extraction_logs_game_id_fkey" in r.getMessage()
               for r in caplog.records if r.levelno == logging.WARNING)
