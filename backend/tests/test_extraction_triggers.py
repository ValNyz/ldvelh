"""#17: resolver-inferred extractors run only for new entities absent from the registry."""

import logging
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from services.extraction import orchestrator
from services.extraction.orchestrator import EXTRACTOR_MAP, resolver_triggers
from services.extraction.resolver import MentionMapping, ResolutionMap

pytestmark = pytest.mark.integration


def _map(*mappings: MentionMapping) -> ResolutionMap:
    return ResolutionMap(mappings=list(mappings))


def _quai(is_new: bool = True) -> MentionMapping:
    return MentionMapping(mention="le quai", canonical="Le Quai 9",
                          entity_type="location", is_new=is_new)


async def _game(test_pool, test_user, registry_names=()):
    game_id = uuid4()
    async with test_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO games (id, user_id) VALUES ($1, $2)", game_id, test_user["id"])
        for name in registry_names:
            await conn.execute(
                "INSERT INTO entity_registry (game_id, entity_type, name) "
                "VALUES ($1, 'location', $2)", game_id, name)
    return game_id


def _spies():
    instances = {}
    def _cls(name):
        inst = MagicMock()
        inst.run = AsyncMock(return_value={"success": True})
        instances[name] = inst
        return MagicMock(return_value=inst)
    return {k: _cls(k) for k in EXTRACTOR_MAP}, instances


async def _run(test_pool, game_id, resolution_map, triggers):
    spies, _ = _spies()
    with patch.dict(EXTRACTOR_MAP, spies), \
            patch.object(orchestrator, "resolve_entities",
                         AsyncMock(return_value=(resolution_map, None))), \
            patch.object(orchestrator, "_build_first_turn_reference",
                         AsyncMock(return_value=("ref", None))):
        await orchestrator.run_resolve_and_extract(
            test_pool, game_id, 1, triggers, session=MagicMock(),
            assistant_message_id=uuid4(), message_content="texte")
    return spies


async def test_all_existing_mappings_and_no_narrator_trigger_run_nothing(test_pool, test_user):
    game_id = await _game(test_user=test_user, test_pool=test_pool)
    rmap = _map(_quai(is_new=False))
    async with test_pool.acquire() as conn:
        assert await resolver_triggers(conn, game_id, rmap) == set()
    spies = await _run(test_pool, game_id, rmap, [])
    assert all(not cls.called for cls in spies.values())


async def test_new_location_adds_locations(test_pool, test_user):
    game_id = await _game(test_pool, test_user)
    async with test_pool.acquire() as conn:
        assert await resolver_triggers(conn, game_id, _map(_quai())) == {"locations"}


async def test_new_mapping_already_in_registry_does_not_trigger(test_pool, test_user):
    game_id = await _game(test_pool, test_user, ["le quai 9"])
    async with test_pool.acquire() as conn:
        assert await resolver_triggers(conn, game_id, _map(_quai())) == set()


async def test_narrator_triggers_are_kept_for_existing_entities(test_pool, test_user):
    game_id = await _game(test_pool, test_user)
    spies = await _run(test_pool, game_id, _map(_quai(is_new=False)), ["locations"])
    assert spies["locations"].called
    assert not spies["characters"].called


async def test_trigger_log_names_both_origins(test_pool, test_user, caplog):
    game_id = await _game(test_pool, test_user)
    with caplog.at_level(logging.INFO, logger="services.extraction.orchestrator"):
        await _run(test_pool, game_id, _map(_quai()), ["characters"])
    lines = [r.getMessage() for r in caplog.records if "Triggers for game" in r.getMessage()]
    assert len(lines) == 1
    assert "narrator=['characters']" in lines[0] and "resolver=['locations']" in lines[0]
