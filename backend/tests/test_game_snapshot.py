"""GameSnapshot: typed, frozen game state read from the DB for the pipeline (#9 consolidated)."""

import json

import pytest
from pydantic import ValidationError

from repos.games import get_snapshot


async def test_new_game_snapshot(test_pool, test_user):
    from services.game_service import GameService
    game_id = await GameService(test_pool).create_game(test_user["id"])
    async with test_pool.acquire() as conn:
        snap = await get_snapshot(conn, game_id)
    assert snap.id == game_id and snap.world_created is False
    assert snap.current_time == "08h00" and snap.engine == "none"
    assert snap.director.last_cycle is None and snap.director.game_duration == "medium"
    with pytest.raises(ValidationError):
        snap.current_cycle = 5  # frozen


async def test_snapshot_after_world_gen_has_world_and_protagonist(test_pool, test_user):
    from services.game_service import GameService
    from schema import WorldGeneration
    from prompts.examples import WORLD_GENERATION_EXAMPLE
    service = GameService(test_pool)
    game_id = await service.create_game(test_user["id"])
    await service.process_init(game_id, WorldGeneration.model_validate(json.loads(WORLD_GENERATION_EXAMPLE)))
    async with test_pool.acquire() as conn:
        snap = await get_snapshot(conn, game_id)
    assert snap.world_created is True
    assert snap.world_name and snap.protagonist_name and snap.current_location_name


async def test_director_schedule_comes_from_latest_plan(test_pool, test_user):
    from services.game_service import GameService
    game_id = await GameService(test_pool).create_game(test_user["id"])
    async with test_pool.acquire() as conn:
        await conn.execute("UPDATE games SET game_duration = 'short' WHERE id = $1", game_id)
        await conn.execute(
            """INSERT INTO director_plans (game_id, cycle, ig_time, tension_level, narrator_guidance)
               VALUES ($1, 2, '08h00', 3, 'g')""", game_id)
        snap = await get_snapshot(conn, game_id)
    assert (snap.director.last_cycle, snap.director.last_time, snap.director.game_duration) == (2, "08h00", "short")


async def test_unknown_game_is_none(test_pool):
    import uuid
    async with test_pool.acquire() as conn:
        assert await get_snapshot(conn, uuid.uuid4()) is None
