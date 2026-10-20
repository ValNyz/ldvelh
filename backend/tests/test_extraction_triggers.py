"""#17: resolver-inferred extractors run only for new entities absent from the registry."""

import logging
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import asyncpg
import pytest

from repos import entities
from services.extraction import orchestrator
from services.extraction.orchestrator import EXTRACTOR_MAP, resolver_triggers
from services.extraction.resolver import MentionMapping, ResolutionMap
from services.identity.types import EntityRef, ResolvedRef

pytestmark = pytest.mark.integration

LOCATION_ID = uuid4()


def _map(*mappings: MentionMapping) -> ResolutionMap:
    return ResolutionMap(mappings=list(mappings))


def _quai(is_new: bool = True) -> MentionMapping:
    return MentionMapping(
        mention="le quai", canonical="Le Quai 9", entity_type="location", is_new=is_new
    )


async def _game(test_pool, test_user, registry_names=()):
    game_id = uuid4()
    async with test_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO games (id, user_id, language) VALUES ($1, $2, 'fr')",
            game_id,
            test_user["id"],
        )
        for name in registry_names:
            await conn.execute(
                "INSERT INTO entity_registry (game_id, entity_type, name) "
                "VALUES ($1, 'location', $2)",
                game_id,
                name,
            )
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
    with (
        patch.dict(EXTRACTOR_MAP, spies),
        patch.object(
            orchestrator,
            "resolve_entities",
            AsyncMock(return_value=(resolution_map, None)),
        ),
        patch.object(
            orchestrator,
            "_build_first_turn_reference",
            AsyncMock(return_value=("ref", None)),
        ),
    ):
        await orchestrator.run_resolve_and_extract(
            test_pool,
            game_id,
            1,
            triggers,
            session=MagicMock(),
            assistant_message_id=uuid4(),
            message_content="texte",
        )
    return spies


async def test_all_existing_mappings_and_no_narrator_trigger_run_nothing(
    test_pool, test_user
):
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
    lines = [
        r.getMessage() for r in caplog.records if "Triggers for game" in r.getMessage()
    ]
    assert len(lines) == 1
    assert (
        "narrator=['characters']" in lines[0] and "resolver=['locations']" in lines[0]
    )


async def test_accent_case_comparison_is_done_in_sql(test_pool, test_user):
    game_id = await _game(test_pool, test_user, ["écluse"])
    m = MentionMapping(
        mention="l'écluse", canonical="Écluse", entity_type="location", is_new=True
    )
    async with test_pool.acquire() as conn:
        assert await resolver_triggers(conn, game_id, _map(m)) == set()


async def test_mix_of_new_and_existing_mappings_triggers_only_the_new_one(
    test_pool, test_user
):
    game_id = await _game(test_pool, test_user, ["Le Quai 9"])
    new_char = MentionMapping(
        mention="Ana", canonical="Ana", entity_type="character", is_new=True
    )
    async with test_pool.acquire() as conn:
        assert await resolver_triggers(conn, game_id, _map(_quai(), new_char)) == {
            "characters"
        }


async def test_unknown_entity_type_is_dropped(test_pool, test_user):
    game_id = await _game(test_pool, test_user)
    arc = MentionMapping(mention="x", canonical="X", entity_type="arc", is_new=True)
    async with test_pool.acquire() as conn:
        assert await resolver_triggers(conn, game_id, _map(arc)) == set()


async def test_lookup_failure_keeps_narrator_triggers(
    test_pool, test_user, caplog, monkeypatch
):
    game_id = await _game(test_pool, test_user)
    monkeypatch.setattr(
        orchestrator, "resolver_triggers", AsyncMock(side_effect=RuntimeError("boom"))
    )
    with caplog.at_level(logging.INFO, logger="services.extraction.orchestrator"):
        spies = await _run(test_pool, game_id, _map(_quai()), ["characters"])
    assert spies["characters"].called and not spies["locations"].called
    assert any(
        r.levelno == logging.WARNING and "lookup failed" in r.getMessage()
        for r in caplog.records
    )


# =============================================================================
# Phase 3 entity_reveals re-apply is guarded by the source message (#23)
# =============================================================================

REVEALS = {
    "entity_reveals": [
        {"entity_type": "character", "current_name": "L'inconnu", "real_name": "Ana"},
        {"entity_type": "location", "current_name": "Le Quai 9"},
    ]
}


async def _assistant_message(test_pool, test_user):
    from domain.turn import NarrationState
    from repos import turns
    from services.game_service import GameService

    game_id = await GameService(test_pool).create_game(test_user["id"])
    state = NarrationState(cycle=1, time="", location=None, npcs_present=[], date=None)
    async with test_pool.acquire() as conn:
        _, assistant_id = await turns.save_turn_messages(
            conn,
            game_id,
            user_message="Je pars.",
            assistant_message="Tu pars.",
            state=state,
            narrator_deltas={},
            engine_snapshot=None,
            turn_id=None,
        )
    return game_id, assistant_id


async def _reapply(test_pool, game_id, assistant_message_id, character_error=None):
    """(location repo, identity service) mocks after the re-apply: character reveals go
    to IdentityService.reveal, location reveals to entities.mark_location_accessible, by
    the id the service resolves."""
    location_repo = MagicMock()
    location_repo.mark_location_accessible = AsyncMock()
    identity = MagicMock()
    identity.game_id = game_id
    identity.reveal = AsyncMock(side_effect=character_error)
    identity.require_live_ref = AsyncMock(
        return_value=ResolvedRef(LOCATION_ID, 1, "Quai", "location")
    )
    with (
        patch.object(
            entities, "mark_location_accessible", location_repo.mark_location_accessible
        ),
        patch.object(
            orchestrator.IdentityService, "for_game", AsyncMock(return_value=identity)
        ),
        patch.object(
            orchestrator, "resolve_entities", AsyncMock(return_value=(None, None))
        ),
    ):
        await orchestrator.run_resolve_and_extract(
            test_pool,
            game_id,
            1,
            [],
            session=MagicMock(),
            assistant_message_id=assistant_message_id,
            message_content="Tu pars.",
            narrator_deltas=REVEALS,
        )
    return location_repo, identity


async def test_reveals_for_a_deleted_source_message_are_not_applied(
    test_pool, test_user
):
    game_id, message_id = await _assistant_message(test_pool, test_user)
    async with test_pool.acquire() as conn:
        await conn.execute("DELETE FROM messages WHERE id = $1", message_id)
    location_repo, identity = await _reapply(test_pool, game_id, message_id)
    identity.reveal.assert_not_called()
    location_repo.mark_location_accessible.assert_not_called()


async def test_reveals_for_a_live_source_message_are_applied(test_pool, test_user):
    game_id, message_id = await _assistant_message(test_pool, test_user)
    location_repo, identity = await _reapply(test_pool, game_id, message_id)
    identity.reveal.assert_awaited_once()
    assert identity.reveal.await_args.args[1:] == (
        EntityRef("L'inconnu", "character"),
        "Ana",
    )
    assert identity.reveal.await_args.kwargs["source"] == "reveal"
    location_repo.mark_location_accessible.assert_awaited_once()
    assert location_repo.mark_location_accessible.await_args.args[1:] == (
        game_id,
        LOCATION_ID,
    )


async def test_reveals_without_source_message_are_applied(test_pool, test_user):
    game_id = await _game(test_pool, test_user)
    location_repo, identity = await _reapply(test_pool, game_id, None)
    identity.reveal.assert_awaited_once()
    location_repo.mark_location_accessible.assert_awaited_once()


async def test_a_failing_reveal_does_not_stop_the_next_one(
    test_pool, test_user, caplog
):
    game_id, message_id = await _assistant_message(test_pool, test_user)
    with caplog.at_level(logging.WARNING):
        location_repo, identity = await _reapply(
            test_pool,
            game_id,
            message_id,
            character_error=asyncpg.UniqueViolationError("L'inconnu"),
        )
    identity.reveal.assert_awaited_once()
    location_repo.mark_location_accessible.assert_awaited_once()
    warnings = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("entity_reveal character item failed" in w for w in warnings)
    assert not any("L'inconnu" in w for w in warnings)
