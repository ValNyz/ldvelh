"""World generation (InitFlow): pure payload, unparsable world, genre from the wizard slug."""

import json
import logging
from uuid import uuid4

import pytest
from pydantic import ValidationError

from domain.game import GameSnapshot
from llm.session import LLMSession
from pipeline import init_flow
from pipeline.context import InitParams, TurnContext, TurnRequest
from pipeline.errors import TurnError
from repos.games import get_snapshot
from services.engine import get_engine
from services.game_service import GameService
from tests.characterization.scripted_llm import ScriptedLLMProvider


class _RecordingSink:
    def __init__(self):
        self.events: list[tuple[str, tuple]] = []

    def __getattr__(self, name):
        if not name.startswith("send_"):
            raise AttributeError(name)

        async def record(*args, **kwargs):
            self.events.append((name, args))
        return record


def _init(engine="none", world_config=None) -> InitParams:
    return InitParams(engine=engine, world_config=world_config, character_data=None,
                      manual_entities=None)


INIT_RESULT = {
    "world": {"name": "Station Azur"},
    "protagonist": {"name": "Valentin"},
    "ai": {"name": "Nova"},
    "npc_count": 3,
    "location_count": 4,
    "org_count": 1,
    "inventory_count": 2,
    "arrival": None,
}
CLIENT_STATE = {"game": {"id": "g"}, "player": {"name": "Valentin"}, "ai": None}


def test_world_payload_counts_and_engine():
    cost = {"total": 0.01}
    payload = init_flow.build_world_payload(CLIENT_STATE, INIT_RESULT, _init("none"), {}, cost)
    assert payload.world_info.npc_count == 3
    assert payload.world_info.location_count == 4
    assert payload.game_state.engine is None
    assert payload.game_state.world_created is True
    assert payload.meta.narration_cost == cost

    payload = init_flow.build_world_payload(CLIENT_STATE, INIT_RESULT, _init("fate_core"), {}, None)
    assert payload.game_state.engine == "fate_core"
    assert payload.meta is None


async def _ctx(pool, user, responses, init: InitParams) -> tuple[TurnContext, _RecordingSink]:
    game_id = await GameService(pool).create_game(user["id"])
    async with pool.acquire() as conn:
        snapshot = await get_snapshot(conn, game_id)
    sink = _RecordingSink()
    session = LLMSession.from_provider(ScriptedLLMProvider(responses))
    request = TurnRequest(game_id=game_id, user_id=user["id"], message="__INIT__", init=init)
    return TurnContext(request=request, snapshot=snapshot, session=session, sink=sink, pool=pool,
                       engine=get_engine(snapshot.engine), ref="test"), sink


async def test_unparsable_world_raises_world_gen_failed(test_pool, test_user):
    ctx, sink = await _ctx(test_pool, test_user, {"world_gen": "pas du JSON"}, _init())
    with pytest.raises(TurnError) as exc:
        await init_flow.run_init(ctx)
    assert exc.value.code == "world_gen_failed"
    assert exc.value.message == "Échec de génération du monde. Réessaie."
    async with test_pool.acquire() as conn:
        count = await conn.fetchval("SELECT COUNT(*) FROM locations WHERE game_id = $1",
                                    ctx.request.game_id)
    assert count == 0
    assert not [e for e in sink.events if e[0] in ("send_done", "send_error")]


async def test_unparsable_world_logs_length_only_at_warning(test_pool, test_user, caplog,
                                                            log_prompts):
    tail = "le dragon de verre murmure"
    ctx, _ = await _ctx(test_pool, test_user, {"world_gen": "pas du JSON " + tail}, _init())
    with caplog.at_level(logging.DEBUG), pytest.raises(TurnError):
        await init_flow.run_init(ctx)
    warned = [r.getMessage() for r in caplog.records
              if r.levelno >= logging.WARNING and "[INIT]" in r.getMessage()]
    assert warned == [f"[INIT] Unparsable world: length={len('pas du JSON ' + tail)}"]
    assert any(tail in r.getMessage() for r in caplog.records if r.levelno == logging.DEBUG)


async def test_invalid_world_schema_raises_world_gen_failed(test_pool, test_user):
    ctx, sink = await _ctx(test_pool, test_user, {"world_gen": json.dumps({"world": "pas un objet"})},
                           _init())
    with pytest.raises(TurnError) as exc:
        await init_flow.run_init(ctx)
    assert exc.value.code == "world_gen_failed"
    assert exc.value.message == "Échec de génération du monde. Réessaie."
    assert isinstance(exc.value.__cause__, ValidationError)
    async with test_pool.acquire() as conn:
        count = await conn.fetchval("SELECT COUNT(*) FROM locations WHERE game_id = $1",
                                    ctx.request.game_id)
    assert count == 0


async def test_resolve_genre_from_wizard_slug_is_stored(test_pool, test_user, seeded_genres):
    ctx, _ = await _ctx(test_pool, test_user, {}, _init(world_config={"genre": "dark_fantasy"}))
    assert ctx.snapshot.genre_id is None
    async with test_pool.acquire() as conn:
        genre = await init_flow.resolve_genre(conn, ctx.snapshot, ctx.request.init)
        stored = await conn.fetchval("SELECT genre_id FROM games WHERE id = $1",
                                     ctx.request.game_id)
    assert genre["slug"] == "dark_fantasy"
    assert stored == genre["id"]


async def test_resolve_genre_prefers_the_game_genre(test_pool, test_user, seeded_genres):
    async with test_pool.acquire() as conn:
        genre_id = await conn.fetchval("SELECT id FROM genres WHERE slug = 'sci_fi'")
    snapshot = GameSnapshot(id=uuid4(), world_created=False, current_cycle=0,
                            current_time="08h00", genre_id=genre_id)
    async with test_pool.acquire() as conn:
        genre = await init_flow.resolve_genre(conn, snapshot,
                                              _init(world_config={"genre": "dark_fantasy"}))
    assert genre["slug"] == "sci_fi"
