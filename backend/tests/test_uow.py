"""The unit of work (repos.uow, #105): one transaction, the turn id set for it only,
the source message share-locked before any write."""

import asyncio
from uuid import uuid4

import pytest

from domain.errors import SourceMessageGone
from domain.turn import NarrationState
from repos import turns
from repos.uow import current_turn_id, uow

pytestmark = pytest.mark.integration


@pytest.fixture
async def game(test_pool, test_user):
    from services.game_service import GameService

    return await GameService(test_pool).create_game(test_user["id"])


@pytest.fixture
async def turn(test_pool, game):
    async with test_pool.acquire() as conn:
        return await turns.open_turn(conn, game)


async def _message(pool, game_id):
    state = NarrationState(cycle=1, time="", location=None, npcs_present=[], date=None)
    async with pool.acquire() as conn:
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
    return assistant_id


async def _organizations(conn, game_id) -> int:
    return await conn.fetchval(
        "SELECT count(*) FROM organizations WHERE game_id = $1", game_id
    )


async def test_uow_sets_the_turn_id_for_the_transaction_only(test_pool, turn):
    async with test_pool.acquire() as conn:
        assert await current_turn_id(conn) is None
        async with uow(conn, turn) as inner:
            assert inner is conn
            assert conn.is_in_transaction()
            assert await current_turn_id(conn) == turn
        assert not conn.is_in_transaction()
        assert await current_turn_id(conn) is None


async def test_uow_without_turn_sets_nothing(test_pool):
    async with test_pool.acquire() as conn, uow(conn, None):
        assert conn.is_in_transaction()
        assert await current_turn_id(conn) is None


async def test_uow_holds_the_source_message_first(test_pool, game, turn):
    async with test_pool.acquire() as conn:
        with pytest.raises(SourceMessageGone):
            async with uow(conn, turn, source_message_id=uuid4()):
                await conn.execute(
                    "INSERT INTO organizations (game_id, name) VALUES ($1, 'Jamais')",
                    game,
                )
        assert await _organizations(conn, game) == 0

    message_id = await _message(test_pool, game)

    async def delete():
        async with test_pool.acquire() as conn_b:
            await conn_b.execute("DELETE FROM messages WHERE id = $1", message_id)

    async with (
        test_pool.acquire() as conn_a,
        uow(conn_a, turn, source_message_id=message_id),
    ):
        deleting = asyncio.create_task(delete())
        await asyncio.sleep(0.2)
        assert not deleting.done()
    await asyncio.wait_for(deleting, 5)
    async with test_pool.acquire() as conn:
        assert (
            await conn.fetchval("SELECT 1 FROM messages WHERE id = $1", message_id)
            is None
        )


async def test_uow_rolls_back_on_error(test_pool, game, turn):
    async with test_pool.acquire() as conn:
        with pytest.raises(RuntimeError):
            async with uow(conn, turn):
                await conn.execute(
                    "INSERT INTO organizations (game_id, name) VALUES ($1, 'Annulée')",
                    game,
                )
                raise RuntimeError("boom")
        assert await _organizations(conn, game) == 0
        assert (
            await conn.fetchval(
                "SELECT count(*) FROM world_changes WHERE turn_id = $1", turn
            )
            == 0
        )


async def test_uow_refuses_to_nest_in_an_open_transaction(test_pool, turn):
    async with test_pool.acquire() as conn, conn.transaction():
        with pytest.raises(RuntimeError, match="top-level transaction"):
            async with uow(conn, turn):
                pass
        assert await current_turn_id(conn) is None
