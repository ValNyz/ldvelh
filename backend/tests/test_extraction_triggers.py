"""#17, #154: the extractors run for the entity types the turn's resolution really
created or left bare (a stub without description), plus the narrator's triggers."""

import logging
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import asyncpg
import pytest

from config import get_identity_config
from domain.identity import EntityRef, NewEntitySpec, ResolvedRef, TurnResolution
from repos import entities
from services.extraction import orchestrator
from services.extraction.orchestrator import EXTRACTOR_MAP, resolver_triggers
from services.identity.service import IdentityService

pytestmark = pytest.mark.integration

LOCATION_ID = uuid4()


def _resolution(*new_types: str) -> TurnResolution:
    return TurnResolution(
        mentions=[], created=[], aliases_added=0, reveals=[], scene_entities=[],
        new_types=set(new_types), escalated=False, fallback=False,
    )


async def _game(test_pool, test_user):
    game_id = uuid4()
    async with test_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO games (id, user_id, language) VALUES ($1, $2, 'fr')",
            game_id,
            test_user["id"],
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


async def _run(test_pool, game_id, resolution, triggers):
    spies, _ = _spies()
    with (
        patch.dict(EXTRACTOR_MAP, spies),
        patch.object(orchestrator, "resolve_phase", AsyncMock(return_value=resolution)),
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


def test_nothing_resolved_adds_nothing():
    assert resolver_triggers(None) == set()
    assert resolver_triggers(_resolution()) == set()


def test_new_or_bare_types_add_their_extractor():
    assert resolver_triggers(_resolution("location")) == {"locations"}
    assert resolver_triggers(_resolution("character", "object")) == {
        "characters",
        "inventory",
    }


def test_types_without_extractor_are_dropped():
    assert resolver_triggers(_resolution("arc", "protagonist")) == set()


async def test_no_new_type_and_no_narrator_trigger_run_nothing(test_pool, test_user):
    game_id = await _game(test_pool, test_user)
    spies = await _run(test_pool, game_id, _resolution(), [])
    assert all(not cls.called for cls in spies.values())


async def test_narrator_triggers_are_kept_for_existing_entities(test_pool, test_user):
    game_id = await _game(test_pool, test_user)
    spies = await _run(test_pool, game_id, _resolution(), ["locations"])
    assert spies["locations"].called
    assert not spies["characters"].called


async def test_trigger_log_names_both_origins(test_pool, test_user, caplog):
    game_id = await _game(test_pool, test_user)
    with caplog.at_level(logging.INFO, logger="services.extraction.orchestrator"):
        await _run(test_pool, game_id, _resolution("location"), ["characters"])
    lines = [
        r.getMessage() for r in caplog.records if "Triggers for game" in r.getMessage()
    ]
    assert len(lines) == 1
    assert (
        "narrator=['characters']" in lines[0] and "resolver=['locations']" in lines[0]
    )


async def test_a_failed_resolution_keeps_narrator_triggers(test_pool, test_user):
    game_id = await _game(test_pool, test_user)
    spies = await _run(test_pool, game_id, None, ["characters"])
    assert spies["characters"].called and not spies["locations"].called


async def test_only_entities_without_description_are_bare(test_pool, test_user):
    game_id = await _game(test_pool, test_user)
    service = IdentityService(game_id, lang="fr", config=get_identity_config())
    async with test_pool.acquire() as conn:
        stub = await service.create_entity(
            conn, NewEntitySpec("location", "Quai 9", "proper_name"),
            turn_id=None, source="resolver",
        )
        described = await service.create_entity(
            conn,
            NewEntitySpec("location", "Halle aux Cordiers", "proper_name",
                          fields={"description": "Une halle couverte."}),
            turn_id=None, source="world_gen",
        )
        bare = await entities.bare_entities(conn, [stub, described])
    assert bare == {stub: "location"}


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
        patch.object(orchestrator, "resolve_phase", AsyncMock(return_value=None)),
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
