"""Rollback is atomic and survives locations created after the target cycle (#11)."""

import pytest

from schema import NarrationOutput
from services.game_service import RollbackRejected
from tests.test_game_and_populator import _make_narration_output, _setup_game_with_world


async def _two_cycles_with_stub_location(client, test_user, test_pool):
    """Cycle 1: one exchange. Cycle 2: the narrator moves the player to an unknown place."""
    game_id, service, world_gen = await _setup_game_with_world(client, test_user, test_pool)
    arrival_loc = world_gen.arrival_event.arrival_location_ref

    first = NarrationOutput.model_validate(_make_narration_output(arrival_loc))
    await service.process_light(game_id, first, current_cycle=1)
    await service.save_messages(
        game_id, "Je regarde autour.", "Rien de neuf.", cycle=1,
        time="09h15", location_ref=arrival_loc, game_date="Lundi 18 Juillet 2847",
    )

    second = NarrationOutput.model_validate(_make_narration_output(
        "Dock 9",
        day_transition={"new_cycle": 2, "new_date": "Mardi 19 Juillet 2847"},
        credit_delta={"amount": -30, "description": "billet de navette"},
    ))
    await service.process_light(game_id, second, current_cycle=1)
    await service.apply_narrator_deltas(game_id, second, 2)
    _, _ = await service.save_messages(
        game_id, "Je prends la navette vers Dock 9.", "La navette arrive au Dock 9.",
        cycle=2, time="08h00", location_ref="Dock 9", game_date="Mardi 19 Juillet 2847",
        narrator_deltas={"credit_delta": {"amount": -30, "description": "billet de navette"}},
    )
    # Extractors stamp facts with the cycle before the day transition, so a cycle-1
    # fact can point at the cycle-2 stub location (second FK path of #11).
    async with test_pool.acquire() as conn:
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
            fact_location = await conn.fetchval(
                "SELECT location_id FROM facts WHERE game_id = $1 AND description LIKE '%Dock 9%'", game_id)
        assert fact_location is None  # fact kept, its deleted location cleared

    @pytest.mark.asyncio
    async def test_failure_midway_leaves_everything_unchanged(self, client, test_user, test_pool, monkeypatch):
        game_id, service, _ = await _two_cycles_with_stub_location(client, test_user, test_pool)
        before = await _state(test_pool, game_id)

        async def boom(self, conn, target_cycle):
            raise RuntimeError("KG rollback failed")

        from kg.populator import KnowledgeGraphPopulator
        monkeypatch.setattr(KnowledgeGraphPopulator, "rollback_to_cycle", boom)
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
