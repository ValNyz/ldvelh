"""Director run split in three: collect, call, apply (#96)."""

import ast
import json
import logging
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

import pytest

from llm.session import LLMSession
from prompts.director_prompt import build_director_user_prompt
from schema.director import ArcUpdate, DirectorOutput

BACKEND = Path(__file__).resolve().parent.parent


async def _game_with_world(test_pool, test_user):
    from schema import WorldGeneration
    from services.game_service import GameService
    from tests.prompt_examples import WORLD_GENERATION_EXAMPLE

    service = GameService(test_pool)
    game_id = await service.create_game(test_user["id"])
    await service.process_init(game_id, WorldGeneration.model_validate(json.loads(WORLD_GENERATION_EXAMPLE)))
    return game_id


async def _counts(test_pool, game_id):
    async with test_pool.acquire() as conn:
        plans = await conn.fetchval("SELECT COUNT(*) FROM director_plans WHERE game_id = $1", game_id)
        arcs = await conn.fetchval("SELECT COUNT(*) FROM narrative_arcs WHERE game_id = $1", game_id)
    return plans, arcs


def _plan(*arcs):
    return DirectorOutput(tension_level=3, narrator_guidance="g", arc_updates=list(arcs))


@pytest.mark.asyncio
async def test_collect_returns_none_for_a_missing_game(test_pool):
    from services.director_context import collect_director_context

    async with test_pool.acquire() as conn:
        assert await collect_director_context(conn, uuid4(), 1, "08h00") is None


@pytest.mark.asyncio
async def test_collect_reads_the_last_three_plans_oldest_first(test_pool, test_user):
    from services.director_context import collect_director_context

    game_id = await _game_with_world(test_pool, test_user)
    async with test_pool.acquire() as conn:
        for cycle in (1, 2, 3, 4):
            await conn.execute(
                """INSERT INTO director_plans (game_id, cycle, ig_time, tension_level, narrator_guidance,
                                               created_at)
                   VALUES ($1, $2::int, '08h00', 3, $3, now() + make_interval(secs => $2::int))""",
                game_id, cycle, f"guidance {cycle}",
            )
        ctx = await collect_director_context(conn, game_id, 5, "09h00")

    assert ctx is not None
    assert "Cycle 1 " not in ctx.previous_plans
    positions = [ctx.previous_plans.index(f"**Cycle {c} 08h00**") for c in (2, 3, 4)]
    assert positions == sorted(positions)
    assert ctx.current_cycle == 5 and ctx.current_time == "09h00"


@pytest.mark.asyncio
async def test_user_prompt_matches_the_prompt_builder(test_pool, test_user):
    from services.director_context import collect_director_context

    game_id = await _game_with_world(test_pool, test_user)
    async with test_pool.acquire() as conn:
        ctx = await collect_director_context(conn, game_id, 1, "08h00")
    assert ctx is not None
    assert ctx.user_prompt() == build_director_user_prompt(**asdict(ctx))


@pytest.mark.asyncio
async def test_apply_is_one_transaction(test_pool, test_user, monkeypatch):
    from services import director_apply

    game_id = await _game_with_world(test_pool, test_user)
    before = await _counts(test_pool, game_id)

    async def boom(*args, **kwargs):
        raise RuntimeError("injected")

    monkeypatch.setattr(director_apply, "_update_last_director_time", boom)
    plan = _plan(ArcUpdate(action="create", title="Arc A", intensity=2))
    async with test_pool.acquire() as conn:
        with pytest.raises(RuntimeError):
            await director_apply.apply_director_plan(conn, game_id, plan, cycle=1, ig_time="08h00",
                                                     source_message_id=None)
    assert await _counts(test_pool, game_id) == before


@pytest.mark.asyncio
async def test_failed_arc_update_is_recorded_alone(test_pool, test_user, caplog):
    from services.director_apply import apply_director_plan

    game_id = await _game_with_world(test_pool, test_user)
    plans_before, arcs_before = await _counts(test_pool, game_id)
    plan = _plan(
        ArcUpdate(action="create", title="Arc valide", intensity=2),
        ArcUpdate(action="create", title="Arc secret fautif", intensity=99),
    )
    caplog.set_level(logging.WARNING)
    async with test_pool.acquire() as conn:
        done = await apply_director_plan(conn, game_id, plan, cycle=1, ig_time="10h00",
                                         source_message_id=None)
        last = await conn.fetchval("SELECT last_director_time FROM games WHERE id = $1", game_id)

    assert done is True
    assert await _counts(test_pool, game_id) == (plans_before + 1, arcs_before + 1)
    assert last == "10h00"
    warnings = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("arc item failed" in w for w in warnings)
    assert not any("Arc secret fautif" in w for w in warnings)


@pytest.mark.asyncio
async def test_apply_drops_the_plan_when_the_source_message_is_gone(test_pool, test_user, caplog):
    from services.director_apply import apply_director_plan

    game_id = await _game_with_world(test_pool, test_user)
    before = await _counts(test_pool, game_id)
    caplog.set_level(logging.WARNING)
    async with test_pool.acquire() as conn:
        done = await apply_director_plan(conn, game_id, _plan(ArcUpdate(action="create", title="A")),
                                         cycle=1, ig_time="08h00", source_message_id=uuid4())
    assert done is False
    assert await _counts(test_pool, game_id) == before
    assert any(f"[DIRECTOR] Source message gone, plan dropped game={game_id}" in r.getMessage()
               for r in caplog.records)


@pytest.mark.asyncio
async def test_apply_keeps_the_plan_when_the_source_message_exists(test_pool, test_user):
    from domain.turn import NarrationState
    from repos import turns
    from services.director_apply import apply_director_plan

    game_id = await _game_with_world(test_pool, test_user)
    plans_before, _ = await _counts(test_pool, game_id)
    state = NarrationState(cycle=1, time="08h00", location=None, npcs_present=[], date=None)
    async with test_pool.acquire() as conn:
        _, message_id = await turns.save_turn_messages(
            conn, game_id, user_message="Je pars.", assistant_message="Tu pars.",
            state=state, narrator_deltas={}, engine_snapshot=None, turn_id=None,
        )
        done = await apply_director_plan(conn, game_id, _plan(), cycle=1, ig_time="08h00",
                                         source_message_id=message_id)
    assert done is True
    plans_after, _ = await _counts(test_pool, game_id)
    assert plans_after == plans_before + 1


class _CountingPool:
    def __init__(self, pool):
        self.pool, self.in_use = pool, 0

    @asynccontextmanager
    async def acquire(self):
        self.in_use += 1
        try:
            async with self.pool.acquire() as conn:
                yield conn
        finally:
            self.in_use -= 1


@pytest.mark.asyncio
async def test_run_director_holds_no_connection_during_the_call(test_pool, test_user):
    from services.director_service import run_director
    from tests.test_llm_session import FakeProvider

    game_id = await _game_with_world(test_pool, test_user)
    pool = _CountingPool(test_pool)
    seen = []

    class CheckingProvider(FakeProvider):
        async def complete(self, *args, **kwargs):
            seen.append(pool.in_use)
            assert pool.in_use == 0
            return await FakeProvider.complete(self, *args, **kwargs)

    session = LLMSession.from_provider(
        CheckingProvider(text=json.dumps({"tension_level": 2, "narrator_guidance": "g"})))
    result = await run_director(pool, game_id, 1, "08h00", session)

    assert seen == [0]
    assert result is not None and result["tension_level"] == 2


def test_run_director_is_thin():
    tree = ast.parse((BACKEND / "services/director_service.py").read_text(encoding="utf-8"))
    func = next(f for f in tree.body
                if isinstance(f, ast.AsyncFunctionDef) and f.name == "run_director")
    assert func.end_lineno is not None
    assert func.end_lineno - func.lineno + 1 < 80
