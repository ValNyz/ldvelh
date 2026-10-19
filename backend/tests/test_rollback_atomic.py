"""Rollback is atomic and survives locations created after the target cycle (#11, #22)."""

import pytest

from domain.errors import RollbackRejected
from helpers import apply_deltas, apply_state, open_turn, save_pair
from repos.uow import uow
from schema import NarrationOutput
from services import rollback
from tests.test_game_and_populator import _make_narration_output, _setup_game_with_world


async def _two_cycles_with_stub_location(client, test_user, test_pool):
    """Cycle 1: one exchange. Cycle 2: the narrator moves the player to an unknown place.

    Each exchange is its own turn, its writes journaled under it (#105)."""
    game_id, service, world_gen = await _setup_game_with_world(client, test_user, test_pool)
    arrival_loc = world_gen.arrival_event.arrival_location_ref

    first = NarrationOutput.model_validate(_make_narration_output(arrival_loc))
    first_turn = await open_turn(test_pool, game_id)
    await apply_state(test_pool, game_id, first, 1, turn_id=first_turn)
    await save_pair(
        test_pool, game_id, "Je regarde autour.", "Rien de neuf.", cycle=1,
        time="09h15", location_ref=arrival_loc, game_date="Lundi 18 Juillet 2847",
        turn_id=first_turn,
    )

    second = NarrationOutput.model_validate(_make_narration_output(
        "Dock 9",
        day_transition={"new_cycle": 2, "new_date": "Mardi 19 Juillet 2847"},
        credit_delta={"amount": -30, "description": "billet de navette"},
    ))
    second_turn = await open_turn(test_pool, game_id)
    await apply_state(test_pool, game_id, second, 1, turn_id=second_turn)
    await apply_deltas(test_pool, game_id, second, 2, turn_id=second_turn)
    _, _ = await save_pair(
        test_pool, game_id, "Je prends la navette vers Dock 9.", "La navette arrive au Dock 9.",
        cycle=2, time="08h00", location_ref="Dock 9", game_date="Mardi 19 Juillet 2847",
        narrator_deltas={"credit_delta": {"amount": -30, "description": "billet de navette"}},
        turn_id=second_turn,
    )
    # Extractors stamp facts with the cycle before the day transition, so a cycle-1
    # fact can point at the cycle-2 stub location (second FK path of #11). The extraction
    # runs under the turn it extracts.
    async with test_pool.acquire() as conn, uow(conn, second_turn):
        fact_type = await conn.fetchval("SELECT type FROM facts WHERE game_id = $1 LIMIT 1", game_id)
        await conn.execute(
            """INSERT INTO facts (game_id, cycle, type, description, location_id)
               SELECT $1, 1, $2, 'Le joueur réserve une place pour Dock 9.', id
               FROM locations WHERE game_id = $1 AND name = 'Dock 9'""",
            game_id, fact_type or "action",
        )
    return game_id, service, arrival_loc


async def _state(test_pool, game_id):
    async with test_pool.acquire() as conn:
        return {
            "messages": await conn.fetchval("SELECT COUNT(*) FROM messages WHERE game_id = $1", game_id),
            "credits": await conn.fetchval("SELECT credits FROM protagonists WHERE game_id = $1", game_id),
            "cycle": await conn.fetchval("SELECT current_cycle FROM games WHERE id = $1", game_id),
            "location": await conn.fetchval(
                """SELECT l.name FROM games g JOIN locations l ON l.id = g.current_location_id
                   WHERE g.id = $1""", game_id),
            "dock9": await conn.fetchval(
                "SELECT COUNT(*) FROM locations WHERE game_id = $1 AND name = 'Dock 9'", game_id),
        }


class TestAtomicRollback:
    @pytest.mark.asyncio
    async def test_rollback_across_day_with_stub_location_succeeds(self, client, test_user, test_pool):
        game_id, service, arrival_loc = await _two_cycles_with_stub_location(client, test_user, test_pool)
        before = await _state(test_pool, game_id)
        assert before["location"] == "Dock 9" and before["cycle"] == 2 and before["dock9"] == 1

        result = await service.rollback_to_message(game_id, keep_until_index=2)

        after = await _state(test_pool, game_id)
        assert result["deleted"] == 2 and result["target_cycle"] == 1
        assert after["messages"] == 2
        assert after["cycle"] == 1
        assert after["location"] == arrival_loc
        assert after["dock9"] == 0
        assert after["credits"] == before["credits"] + 30
        async with test_pool.acquire() as conn:
            facts = await conn.fetchval(
                "SELECT count(*) FROM facts WHERE game_id = $1 AND description LIKE '%Dock 9%'",
                game_id)
        assert facts == 0  # the turn's extraction is undone with it, whatever its cycle

    @pytest.mark.asyncio
    async def test_failure_midway_leaves_everything_unchanged(self, client, test_user, test_pool, monkeypatch):
        game_id, service, _ = await _two_cycles_with_stub_location(client, test_user, test_pool)
        before = await _state(test_pool, game_id)

        async def boom(conn, turn_ids):
            raise RuntimeError("KG rollback failed")

        monkeypatch.setattr(rollback, "_undo_changes", boom)
        with pytest.raises(RuntimeError, match="KG rollback failed"):
            await service.rollback_to_message(game_id, keep_until_index=2)

        assert await _state(test_pool, game_id) == before

    @pytest.mark.asyncio
    @pytest.mark.parametrize("index", [0, 1, -1])
    async def test_rolling_back_the_arrival_pair_is_rejected(self, client, test_user, test_pool, index):
        game_id, service, _ = await _two_cycles_with_stub_location(client, test_user, test_pool)
        before = await _state(test_pool, game_id)
        with pytest.raises(RollbackRejected):
            await service.rollback_to_message(game_id, keep_until_index=index)
        assert await _state(test_pool, game_id) == before

    @pytest.mark.asyncio
    async def test_route_returns_400_for_arrival_rollback(self, client, test_user, test_pool):
        game_id, _, _ = await _two_cycles_with_stub_location(client, test_user, test_pool)
        r = await client.post(
            f"/api/games/{game_id}/rollback", json={"fromIndex": 0},
            headers={"Authorization": f"Bearer {test_user['token']}"},
        )
        assert r.status_code == 400
        # #80: a fixed French message, never the exception text.
        assert r.json()["detail"] == "Impossible de revenir avant la scène d'arrivée."
