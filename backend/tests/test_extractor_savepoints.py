"""
Extractor write isolation (#24): each item is written in its own SAVEPOINT, a failed
item never takes the others down, and run() reports what was really committed.
"""

import logging
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from llm.session import LLMSession
from services.extraction.characters import CharactersExtractor
from services.game_service import GameService
from tests.test_llm_session import FakeProvider


async def _extractor(test_pool, test_user, raw_result):
    game_id = await GameService(test_pool).create_game(test_user["id"])
    extractor = CharactersExtractor(test_pool, game_id,
                                    LLMSession.from_provider(FakeProvider()))

    async def fake_call(*args, **kwargs):
        return raw_result, {"cost_usd": 0.001}

    extractor._call_llm = fake_call
    return extractor, game_id


def _fact(key):
    return {"fact_type": "observation", "description": "Une porte grince.",
            "semantic_key": key}


async def _character_names(test_pool, game_id):
    async with test_pool.acquire() as conn:
        rows = await conn.fetch("SELECT name FROM characters WHERE game_id = $1", game_id)
    return {r["name"] for r in rows}


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
    extractor, game_id = await _extractor(test_pool, test_user, raw)
    real_update = extractor.populator.update_entity

    async def colliding_update(conn, entity_type, name, changes):
        if name == "Alpha":  # rename collision: server-side unique violation
            await conn.execute("UPDATE characters SET name = 'Beta' "
                               "WHERE game_id = $1 AND name = 'Alpha'", game_id)
        return await real_update(conn, entity_type, name, changes)

    extractor.populator.update_entity = colliding_update
    result = await extractor.run("texte", {}, 1)

    assert await _character_names(test_pool, game_id) >= {"Alpha", "Beta"}
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
    extractor, game_id = await _extractor(
        test_pool, test_user, {"entities_created": [{"name": "Gamma"}]})
    result = await extractor.run("texte", {}, 1)
    assert result["success"] is True and not result.get("partial")
    assert result["stats"]["errors"] == []
    assert "Gamma" in await _character_names(test_pool, game_id)


async def test_populate_raising_returns_failure(test_pool, test_user):
    extractor, game_id = await _extractor(
        test_pool, test_user, {"entities_created": [{"name": "Delta"}]})
    real_populate = extractor._populate

    async def failing_populate(conn, raw_result, cycle):
        await real_populate(conn, raw_result, cycle)
        raise RuntimeError("db hiccup")

    extractor._populate = failing_populate
    result = await extractor.run("texte", {}, 1)

    assert result["success"] is False and not result.get("partial")
    assert result["cost"] == {"cost_usd": 0.001}
    assert "Delta" not in await _character_names(test_pool, game_id)  # rolled back
    async with test_pool.acquire() as conn:
        logged = await conn.fetchval(
            "SELECT errors FROM extraction_logs WHERE game_id = $1", game_id)
    assert logged and "db hiccup" in logged[0]


async def test_swallowed_sql_error_fails_the_whole_populate(test_pool, test_user):
    """An item that leaves the transaction aborted must not be reported as committed."""
    extractor, game_id = await _extractor(
        test_pool, test_user,
        {"entities_created": [{"name": "Epsilon"}],
         "entities_updated": [{"entity_ref": "Epsilon", "changes": {"mood": "las"}}]})

    async def swallowing_update(conn, entity_type, name, changes):
        try:
            await conn.execute("SELECT 1/0")
        except Exception:
            pass
        return True

    extractor.populator.update_entity = swallowing_update
    result = await extractor.run("texte", {}, 1)

    assert result["success"] is False and not result.get("partial")
    assert "Epsilon" not in await _character_names(test_pool, game_id)


async def test_orchestrator_log_counts_real_outcomes(caplog):
    from services.extraction.orchestrator import (
        EXTRACTOR_MAP,
        _extracting_games,
        run_triggered_extraction,
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
    _extracting_games.clear()
    with patch.dict(EXTRACTOR_MAP, {k: _cls(v) for k, v in outcomes.items()}), \
            caplog.at_level(logging.INFO, logger="services.extraction.orchestrator"):
        await run_triggered_extraction(pool, uuid4(), trigger_cycle=1,
                                       triggers=list(outcomes), session=MagicMock(),
                                       message_content="texte")

    complete = [r.getMessage() for r in caplog.records if "Complete:" in r.getMessage()]
    assert len(complete) == 1
    assert "1 succeeded, 1 partial, 1 failed, 1 skipped (4 extractors)" in complete[0]
