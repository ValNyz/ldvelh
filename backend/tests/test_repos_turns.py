"""Turn writes (repos.turns): narration state, narrator deltas, info requests,
message pair and mechanic rolls, all on the caller's connection."""

from uuid import UUID

import pytest

from domain.turn import NarrationState
from helpers import apply_deltas, apply_state, auth_headers, log_roll, make_roll
from repos import turns
from schema import NarrationOutput
from tests.test_game_and_populator import (
    _make_day_transition_narration,
    _make_narration_output,
    _setup_game_with_world,
)

pytestmark = pytest.mark.integration


def _state(cycle=1, time="", location=None, date=None) -> NarrationState:
    return NarrationState(cycle=cycle, time=time, location=location, npcs_present=[], date=date)


async def _save(pool, game_id, user_message, assistant_message, state=None,
                narrator_deltas=None):
    async with pool.acquire() as conn:
        return await turns.save_turn_messages(
            conn, game_id, user_message=user_message, assistant_message=assistant_message,
            state=state or _state(), narrator_deltas=narrator_deltas, engine_snapshot=None,
        )


async def _store_pending(pool, game_id, roll, message="Je saute.", cycle=1):
    async with pool.acquire() as conn:
        return await turns.store_pending_roll(conn, game_id, roll, message, cycle)


async def _get_pending(pool, game_id):
    async with pool.acquire() as conn:
        return await turns.get_pending_roll(conn, game_id)


async def _claim(pool, game_id, roll_id, roll_details, outcome, message_id):
    async with pool.acquire() as conn:
        return await turns.claim_pending_roll(conn, game_id, roll_id, roll_details, outcome,
                                              message_id)


# =============================================================================
# apply_narration_state (ex process_light)
# =============================================================================


class TestApplyNarrationState:

    async def test_updates_cycle_time_location(self, client, test_user, test_pool):
        game_id, service, world_gen = await _setup_game_with_world(client, test_user, test_pool)
        arrival_loc = world_gen.arrival_event.arrival_location_ref
        narration = NarrationOutput.model_validate(_make_narration_output(arrival_loc))

        result = await apply_state(test_pool, game_id, narration, 1)

        # No day_transition, so cycle stays at 1
        assert result.cycle == 1
        assert result.time == "09h15"
        assert result.location == arrival_loc
        state = await service.load_game_state(game_id)
        assert state["game"]["time"] == "09h15"

    async def test_with_day_transition(self, client, test_user, test_pool):
        game_id, service, world_gen = await _setup_game_with_world(client, test_user, test_pool)
        arrival_loc = world_gen.arrival_event.arrival_location_ref
        narration = NarrationOutput.model_validate(_make_day_transition_narration(arrival_loc))

        result = await apply_state(test_pool, game_id, narration, 1)

        assert result.cycle == 2
        assert result.date == "Mardi 19 Juillet 2847"
        assert result.time == "23h45"
        state = await service.load_game_state(game_id)
        assert state["game"]["current_cycle"] == 2
        assert state["game"]["game_date"] == "Mardi 19 Juillet 2847"

    async def test_creates_stub_location(self, client, test_user, test_pool):
        game_id, _, _ = await _setup_game_with_world(client, test_user, test_pool)
        unknown_loc = "Couloir Technique B-7"
        narration = NarrationOutput.model_validate(_make_narration_output(unknown_loc))

        result = await apply_state(test_pool, game_id, narration, 1)
        assert result.location == unknown_loc

        async with test_pool.acquire() as conn:
            loc_id = await conn.fetchval(
                "SELECT id FROM locations WHERE game_id = $1 AND name = $2", game_id, unknown_loc)
        assert loc_id is not None

    async def test_resolves_existing_location(self, client, test_user, test_pool):
        game_id, _, _ = await _setup_game_with_world(client, test_user, test_pool)
        narration = NarrationOutput.model_validate(_make_narration_output("Le Quart de Cycle"))

        result = await apply_state(test_pool, game_id, narration, 1)
        assert result.location == "Le Quart de Cycle"

        async with test_pool.acquire() as conn:
            loc_id = await conn.fetchval(
                "SELECT current_location_id FROM games WHERE id = $1", game_id)
            loc_name = await conn.fetchval("SELECT name FROM locations WHERE id = $1", loc_id)
        assert loc_name == "Le Quart de Cycle"

    async def test_npcs_present(self, client, test_user, test_pool):
        game_id, _, _ = await _setup_game_with_world(client, test_user, test_pool)
        narration = NarrationOutput.model_validate(
            _make_narration_output("Le Quart de Cycle", npcs_present=["Ossek"]))

        result = await apply_state(test_pool, game_id, narration, 1)
        assert result.npcs_present == ["Ossek"]

    async def test_clears_detail_requests_on_day_transition(self, client, test_user, test_pool):
        game_id, _, world_gen = await _setup_game_with_world(client, test_user, test_pool)
        arrival_loc = world_gen.arrival_event.arrival_location_ref
        async with test_pool.acquire() as conn:
            await turns.store_info_requests(conn, game_id, ["Ossek", "Justine Lépicier"])
            reqs = await conn.fetchval("SELECT detail_requests FROM games WHERE id = $1", game_id)
        assert len(reqs) == 2

        narration = NarrationOutput.model_validate(_make_day_transition_narration(arrival_loc))
        await apply_state(test_pool, game_id, narration, 1)

        async with test_pool.acquire() as conn:
            reqs = await conn.fetchval("SELECT detail_requests FROM games WHERE id = $1", game_id)
        assert reqs == [] or reqs == "{}"


# =============================================================================
# apply_narrator_deltas
# =============================================================================


class TestApplyNarratorDeltas:

    async def test_no_deltas_returns_null_credits(self, client, test_user, test_pool):
        game_id, _, world_gen = await _setup_game_with_world(client, test_user, test_pool)
        narration = NarrationOutput.model_validate(_make_narration_output(
            world_gen.arrival_event.arrival_location_ref, credit_delta=None))

        result = await apply_deltas(test_pool, game_id, narration, 1)

        assert result.credit is None

    async def test_credit_delta_applied(self, client, test_user, test_pool):
        game_id, service, world_gen = await _setup_game_with_world(client, test_user, test_pool)
        credits_before = (await service.load_game_state(game_id))["player"]["credits"]
        narration = NarrationOutput.model_validate(_make_narration_output(
            world_gen.arrival_event.arrival_location_ref,
            credit_delta={"amount": -25, "description": "repas au terminal"}))

        result = await apply_deltas(test_pool, game_id, narration, 1)

        assert result.credit["amount"] == -25
        assert result.credit["new_balance"] == credits_before - 25
        assert result.credit["applied"] is True
        assert result.credit["description"] == "repas au terminal"
        state_after = await service.load_game_state(game_id)
        assert state_after["player"]["credits"] == credits_before - 25

    async def test_entity_reveal_marks_character_known(self, client, test_user, test_pool):
        game_id, _, _ = await _setup_game_with_world(client, test_user, test_pool)
        sql = "SELECT known_by_protagonist FROM characters WHERE game_id = $1 AND name = 'Ossek'"
        async with test_pool.acquire() as conn:
            assert await conn.fetchval(sql, game_id) is False

        narration = NarrationOutput.model_validate(_make_narration_output(
            "Le Quart de Cycle", credit_delta=None,
            entity_reveals=[{"entity_type": "character", "current_name": "Ossek",
                             "real_name": None}]))
        await apply_deltas(test_pool, game_id, narration, 1)

        async with test_pool.acquire() as conn:
            assert await conn.fetchval(sql, game_id) is True

    async def test_entity_reveal_location_accessible(self, client, test_user, test_pool):
        game_id, _, _ = await _setup_game_with_world(client, test_user, test_pool)
        async with test_pool.acquire() as conn:
            await conn.execute(
                "UPDATE locations SET accessible = false"
                " WHERE game_id = $1 AND name = 'Serres Hydro-7'", game_id)

        narration = NarrationOutput.model_validate(_make_narration_output(
            "Le Quart de Cycle", credit_delta=None,
            entity_reveals=[{"entity_type": "location", "current_name": "Serres Hydro-7"}]))
        await apply_deltas(test_pool, game_id, narration, 1)

        async with test_pool.acquire() as conn:
            accessible = await conn.fetchval(
                "SELECT accessible FROM locations"
                " WHERE game_id = $1 AND name = 'Serres Hydro-7'", game_id)
        assert accessible is True


# =============================================================================
# store_info_requests
# =============================================================================


async def test_store_and_retrieve_info_requests(client, test_user, test_pool):
    resp = await client.post("/api/games", headers=auth_headers(test_user["token"]))
    game_id = UUID(resp.json()["gameId"])

    async with test_pool.acquire() as conn:
        await turns.store_info_requests(conn, game_id, ["Ossek", "Justine Lépicier"])
        reqs = await conn.fetchval("SELECT detail_requests FROM games WHERE id = $1", game_id)
    assert "Ossek" in reqs
    assert "Justine Lépicier" in reqs


# =============================================================================
# save_turn_messages (+ load_chat_messages)
# =============================================================================


class TestSaveTurnMessages:

    async def test_save_and_load_messages(self, client, test_user, test_pool):
        game_id, service, world_gen = await _setup_game_with_world(client, test_user, test_pool)

        user_id, assistant_id = await _save(
            test_pool, game_id, "Je regarde autour de moi",
            "Tu observes le terminal. Rien de spécial.",
            _state(1, "09h15", world_gen.arrival_event.arrival_location_ref,
                   "Lundi 18 Juillet 2847"),
        )

        assert user_id is not None
        assert assistant_id is not None
        messages = await service.load_chat_messages(game_id)
        assert len(messages) == 2
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "Je regarde autour de moi"
        assert messages[1]["role"] == "assistant"
        assert messages[1]["content"] == "Tu observes le terminal. Rien de spécial."
        assert messages[0]["cycle"] == 1
        assert messages[0]["time"] == "09h15"

    async def test_protocol_messages_filtered(self, client, test_user, test_pool):
        game_id, service, _ = await _setup_game_with_world(client, test_user, test_pool)
        await _save(test_pool, game_id, "__ARRIVEE__", "Tu arrives sur la station...")
        await _save(test_pool, game_id, "Bonjour", "Le terminal est bruyant.")

        messages = await service.load_chat_messages(game_id)

        user_messages = [m for m in messages if m["role"] == "user"]
        assert len(user_messages) == 1
        assert user_messages[0]["content"] == "Bonjour"
        assistant_messages = [m for m in messages if m["role"] == "assistant"]
        assert len(assistant_messages) == 2

    async def test_save_with_narrator_deltas(self, client, test_user, test_pool):
        game_id, service, _ = await _setup_game_with_world(client, test_user, test_pool)
        deltas = {
            "extraction_triggers": ["characters", "narrative_arcs"],
            "cost": {
                "input_tokens": 1000,
                "output_tokens": 500,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
                "model": "claude-sonnet-4-20250514",
                "provider": "anthropic",
            },
        }
        await _save(test_pool, game_id, "Je parle à Ossek", "Ossek te regarde avec mélancolie.",
                    narrator_deltas=deltas)

        messages = await service.load_chat_messages(game_id)
        assistant_msg = [m for m in messages if m["role"] == "assistant"][0]
        assert "cost" in assistant_msg
        assert assistant_msg["cost"]["input_tokens"] == 1000

    async def test_load_chat_messages_includes_roll_data(self, client, test_user, test_pool):
        game_id, service, _ = await _setup_game_with_world(client, test_user, test_pool)
        _, assistant_id = await _save(test_pool, game_id, "Je tente d'escalader le mur",
                                      "Tu grimpes avec effort.")
        roll = make_roll([-1, 0, 1, 1], 1, "success", skill="Athlétisme", skill_total=4,
                         shifts=2, details={"difficulty": 2})

        await log_roll(test_pool, game_id, roll, message_id=assistant_id)

        messages = await service.load_chat_messages(game_id)
        assistant_msg = [m for m in messages if m["role"] == "assistant"][0]
        assert "roll" in assistant_msg
        assert assistant_msg["roll"]["outcome"] == "success"
        assert assistant_msg["roll"]["dice"] == [-1, 0, 1, 1]
        assert assistant_msg["roll"]["details"]["skill_name"] == "Athlétisme"

    async def test_load_chat_messages_no_roll_returns_no_roll_key(self, client, test_user,
                                                                   test_pool):
        game_id, service, _ = await _setup_game_with_world(client, test_user, test_pool)
        await _save(test_pool, game_id, "Bonjour", "Bienvenue.")

        for msg in await service.load_chat_messages(game_id):
            assert "roll" not in msg


# =============================================================================
# mechanic rolls
# =============================================================================


class TestMechanicRolls:

    async def test_log_mechanic_roll_persists_to_db(self, client, test_user, test_pool):
        game_id, _, _ = await _setup_game_with_world(client, test_user, test_pool)
        _, assistant_id = await _save(test_pool, game_id, "Je tire", "Le blaster fait mouche.")
        roll = make_roll([3, 5, 2, 6], 16, "success", skill="Blasters", skill_total=19,
                         shifts=4, details={"dice_code": "4D", "difficulty": 15})

        await log_roll(test_pool, game_id, roll, message_id=assistant_id, engine="d6")

        async with test_pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM mechanic_rolls WHERE game_id = $1", game_id)
        assert row is not None
        assert row["engine"] == "d6"
        assert row["skill_used"] == "Blasters"
        assert row["outcome"] == "success"
        assert row["complication"] is False
        assert row["cycle"] == 1
        assert row["message_id"] == assistant_id
        assert row["roll_details"]["dice"] == [3, 5, 2, 6]

    async def test_log_mechanic_roll_null_skill(self, client, test_user, test_pool):
        game_id, _, _ = await _setup_game_with_world(client, test_user, test_pool)
        _, assistant_id = await _save(test_pool, game_id, "Test", "Result.")

        await log_roll(test_pool, game_id, make_roll([0, 0, 0, 0], 0, "tie"),
                   message_id=assistant_id)

        async with test_pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM mechanic_rolls WHERE game_id = $1", game_id)
        assert row is not None
        assert row["skill_used"] is None
        assert row["outcome"] == "tie"

    async def test_log_mechanic_roll_with_complication(self, client, test_user, test_pool):
        game_id, _, _ = await _setup_game_with_world(client, test_user, test_pool)
        _, assistant_id = await _save(test_pool, game_id, "Test", "Result.")
        roll = make_roll([4, 1], 4, "failure", skill="Esquive", complication=True,
                         details={"wild_die_rolls": [1]})

        await log_roll(test_pool, game_id, roll, message_id=assistant_id, engine="d6", cycle=2)

        async with test_pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM mechanic_rolls WHERE game_id = $1", game_id)
        assert row["complication"] is True
        assert row["cycle"] == 2

    async def test_multiple_rolls_across_messages(self, client, test_user, test_pool):
        game_id, service, _ = await _setup_game_with_world(client, test_user, test_pool)
        _, aid1 = await _save(test_pool, game_id, "Action 1", "Response 1")
        _, aid2 = await _save(test_pool, game_id, "Action 2", "Response 2")

        await log_roll(test_pool, game_id, make_roll([1, 1, 0, -1], 1, "success", skill="Combat"),
                   message_id=aid1)
        await log_roll(test_pool, game_id,
                   make_roll([-1, -1, 0, 0], -2, "failure", skill="Discrétion"),
                   message_id=aid2)

        assistants = [m for m in await service.load_chat_messages(game_id)
                      if m["role"] == "assistant"]
        assert len(assistants) == 2
        assert assistants[0]["roll"]["dice"] == [1, 1, 0, -1]
        assert assistants[0]["roll"]["outcome"] == "success"
        assert assistants[1]["roll"]["dice"] == [-1, -1, 0, 0]
        assert assistants[1]["roll"]["outcome"] == "failure"

    async def test_log_mechanic_roll_returns_uuid(self, client, test_user, test_pool):
        game_id, _, _ = await _setup_game_with_world(client, test_user, test_pool)
        roll_id = await log_roll(test_pool, game_id,
                             make_roll([0, 0, 0, 0], 0, "failure", skill="Combat"))
        assert roll_id is not None
        assert isinstance(roll_id, UUID)

    async def test_store_and_get_pending_roll(self, client, test_user, test_pool):
        game_id, _, _ = await _setup_game_with_world(client, test_user, test_pool)
        roll = make_roll([-1, 0, 0, -1], -2, "failure", skill="Combat", skill_total=1,
                         shifts=-3, details={"difficulty": 4})
        roll_id = await _store_pending(test_pool, game_id, roll, message="Je frappe.", cycle=2)

        pending = await _get_pending(test_pool, game_id)
        assert pending == {"id": roll_id, "roll": roll.model_dump(), "player_message": "Je frappe."}
        async with test_pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM mechanic_rolls WHERE id = $1", roll_id)
        assert (row["status"], row["message_id"], row["engine"], row["skill_used"],
                row["outcome"], row["cycle"]) == ("pending", None, "fate_core", "Combat",
                                                  "failure", 2)

    async def test_no_pending_roll(self, client, test_user, test_pool):
        game_id, _, _ = await _setup_game_with_world(client, test_user, test_pool)
        _, aid = await _save(test_pool, game_id, "test", "response")
        await log_roll(test_pool, game_id, make_roll([0], 0, "tie"), message_id=aid)
        assert await _get_pending(test_pool, game_id) is None

    async def test_one_pending_roll_per_game(self, client, test_user, test_pool):
        import asyncpg

        game_id, _, _ = await _setup_game_with_world(client, test_user, test_pool)
        await _store_pending(test_pool, game_id, make_roll([0], 0, "failure"))
        with pytest.raises(asyncpg.UniqueViolationError):
            await _store_pending(test_pool, game_id, make_roll([0], 0, "failure"))

    async def test_claim_resolves_once(self, client, test_user, test_pool):
        game_id, _, _ = await _setup_game_with_world(client, test_user, test_pool)
        roll_id = await _store_pending(test_pool, game_id,
                                       make_roll([-1, 0, 0, -1], -2, "failure", skill="Combat"))
        _, aid = await _save(test_pool, game_id, "test", "response")
        final = {"dice": [-1, 0, 0, -1], "total": -2, "details": {"invoked_aspects": ["A"]}}

        assert await _claim(test_pool, game_id, roll_id, final, "success", aid) is True
        assert await _get_pending(test_pool, game_id) is None
        async with test_pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM mechanic_rolls WHERE id = $1", roll_id)
        assert (row["status"], row["outcome"], row["message_id"]) == ("resolved", "success", aid)
        assert row["roll_details"]["details"]["invoked_aspects"] == ["A"]
        # Second claim of the same roll: refused, nothing changes.
        assert await _claim(test_pool, game_id, roll_id, {"dice": []}, "tie", aid) is False

    async def test_claim_checks_the_game(self, client, test_user, test_pool):
        from uuid import uuid4

        game_id, _, _ = await _setup_game_with_world(client, test_user, test_pool)
        roll_id = await _store_pending(test_pool, game_id, make_roll([0], 0, "failure"))
        _, aid = await _save(test_pool, game_id, "test", "response")
        assert await _claim(test_pool, uuid4(), roll_id, {}, "tie", aid) is False
        assert (await _get_pending(test_pool, game_id))["id"] == roll_id


# =============================================================================
# One transaction: the caller owns it
# =============================================================================


async def test_writes_share_the_callers_transaction(client, test_user, test_pool):
    """Every write goes through the caller's connection: a ROLLBACK leaves nothing."""
    game_id, service, world_gen = await _setup_game_with_world(client, test_user, test_pool)
    narration = NarrationOutput.model_validate(_make_narration_output(
        "Dock 9", credit_delta={"amount": -30, "description": "billet"},
        info_requests=["Ossek"],
        day_transition={"new_cycle": 2, "new_date": "Mardi 19 Juillet 2847"}))

    async def counts(conn):
        return {
            "cycle": await conn.fetchval("SELECT current_cycle FROM games WHERE id = $1", game_id),
            "requests": await conn.fetchval(
                "SELECT detail_requests FROM games WHERE id = $1", game_id),
            "messages": await conn.fetchval(
                "SELECT count(*) FROM messages WHERE game_id = $1", game_id),
            "rolls": await conn.fetchval(
                "SELECT count(*) FROM mechanic_rolls WHERE game_id = $1", game_id),
            "dock": await conn.fetchval(
                "SELECT count(*) FROM locations WHERE game_id = $1 AND name = 'Dock 9'", game_id),
        }

    credits_before = (await service.load_game_state(game_id))["player"]["credits"]
    async with test_pool.acquire() as conn:
        before = await counts(conn)
        tx = conn.transaction()
        await tx.start()
        state = await turns.apply_narration_state(conn, game_id, narration, 1)
        await turns.apply_narrator_deltas(conn, game_id, narration, state.cycle)
        await turns.store_info_requests(conn, game_id, narration.info_requests)
        _, assistant_id = await turns.save_turn_messages(
            conn, game_id, user_message="Je pars.", assistant_message="Tu pars.",
            state=state, narrator_deltas={}, engine_snapshot=None)
        await turns.log_mechanic_roll(conn, game_id, message_id=assistant_id, engine="fate_core",
                                      roll=make_roll([1, 1, 1, 1], 4, "success"), cycle=2)
        assert (await counts(conn))["messages"] == before["messages"] + 2
        await tx.rollback()
        after = await counts(conn)

    assert after == before
    assert (await service.load_game_state(game_id))["player"]["credits"] == credits_before
