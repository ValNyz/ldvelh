"""
Integration tests for GameService and ExtractionPopulator.
Uses the real test database — no LLM calls (mocked data).

Covers:
  - GameService: process_light, apply_narrator_deltas, save_messages,
    rollback_to_message, load_chat_messages, load_game_state, load_world_info,
    verify_ownership, store_info_requests, build_llm_messages
  - ExtractionPopulator: process_extraction with facts, entities, relations,
    arcs, events, objects, credit changes, inventory, ambient updates
"""

import json
from uuid import UUID

import pytest

from helpers import auth_headers
from prompts.examples import WORLD_GENERATION_EXAMPLE

pytestmark = pytest.mark.integration


# =============================================================================
# SHARED HELPERS
# =============================================================================


def _make_narration_output(location: str, **overrides) -> dict:
    """Build a minimal valid NarrationOutput dict."""
    base = {
        "narrative_text": (
            "Valentin pousse la porte du terminal et observe les alentours. "
            "L'air recyclé sent le métal et le café tiède. "
            "Quelques voyageurs traînent leurs bagages sur le sol usé."
        ),
        "time": {"new_time": "09h15", "ellipse": False},
        "current_location": location,
        "npcs_present": [],
        "credit_delta": {"amount": -15, "description": "café au terminal"},
        "inventory_hints": [],
        "entity_reveals": [],
        "events_mentioned": [],
        "info_requests": [],
        "extraction_triggers": [],
    }
    base.update(overrides)
    return base


def _make_day_transition_narration(location: str) -> dict:
    """Build a NarrationOutput with day_transition."""
    return _make_narration_output(
        location,
        narrative_text=(
            "La fatigue finit par avoir raison de toi. Tu t'écroules sur le lit "
            "étroit, sans même prendre la peine de te déshabiller. Le plafond "
            "tacheté te regarde fixement."
        ),
        time={"new_time": "23h45", "ellipse": False},
        day_transition={
            "new_cycle": 2,
            "new_date": "Mardi 19 Juillet 2847",
            "night_summary": "Nuit agitée, rêves confus.",
        },
        credit_delta=None,
    )


async def _setup_game_with_world(client, test_user, test_pool):
    """Create a game and populate the world. Returns (game_id, service, world_gen)."""
    from schema import WorldGeneration
    from services.game_service import GameService

    resp = await client.post("/api/games", headers=auth_headers(test_user["token"]))
    assert resp.status_code == 200
    game_id = UUID(resp.json()["gameId"])

    world_gen_data = json.loads(WORLD_GENERATION_EXAMPLE)
    world_gen = WorldGeneration.model_validate(world_gen_data)

    service = GameService(test_pool)
    await service.process_init(game_id, world_gen)

    return game_id, service, world_gen


# =============================================================================
# GAME SERVICE - process_light
# =============================================================================


class TestProcessLight:
    """Tests for GameService.process_light()"""

    @pytest.mark.asyncio
    async def test_process_light_updates_cycle_time_location(
        self, client, test_user, test_pool
    ):
        """process_light updates game cycle, time, and location in the DB."""
        from schema import NarrationOutput

        game_id, service, world_gen = await _setup_game_with_world(
            client, test_user, test_pool
        )
        arrival_loc = world_gen.arrival_event.arrival_location_ref

        narration_data = _make_narration_output(arrival_loc)
        narration = NarrationOutput.model_validate(narration_data)

        result = await service.process_light(game_id, narration, current_cycle=1)

        # No day_transition, so cycle stays at 1
        assert result["cycle"] == 1
        assert result["time"] == "09h15"
        assert result["location"] == arrival_loc

        # Verify DB reflects the update
        state = await service.load_game_state(game_id)
        assert state["game"]["time"] == "09h15"

    @pytest.mark.asyncio
    async def test_process_light_with_day_transition(
        self, client, test_user, test_pool
    ):
        """process_light increments cycle and updates date on day_transition."""
        from schema import NarrationOutput

        game_id, service, world_gen = await _setup_game_with_world(
            client, test_user, test_pool
        )
        arrival_loc = world_gen.arrival_event.arrival_location_ref

        narration_data = _make_day_transition_narration(arrival_loc)
        narration = NarrationOutput.model_validate(narration_data)

        result = await service.process_light(game_id, narration, current_cycle=1)

        assert result["cycle"] == 2
        assert result["date"] == "Mardi 19 Juillet 2847"
        assert result["time"] == "23h45"

        # Verify the DB was updated
        state = await service.load_game_state(game_id)
        assert state["game"]["current_cycle"] == 2
        assert state["game"]["game_date"] == "Mardi 19 Juillet 2847"

    @pytest.mark.asyncio
    async def test_process_light_creates_stub_location(
        self, client, test_user, test_pool
    ):
        """process_light creates a stub location if the narrated location doesn't exist."""
        from schema import NarrationOutput

        game_id, service, world_gen = await _setup_game_with_world(
            client, test_user, test_pool
        )

        # Use a location name that does NOT exist in the world
        unknown_loc = "Couloir Technique B-7"
        narration_data = _make_narration_output(unknown_loc)
        narration = NarrationOutput.model_validate(narration_data)

        result = await service.process_light(game_id, narration, current_cycle=1)
        assert result["location"] == unknown_loc

        # Verify the stub location was created
        async with test_pool.acquire() as conn:
            loc_id = await conn.fetchval(
                "SELECT id FROM locations WHERE game_id = $1 AND name = $2",
                game_id,
                unknown_loc,
            )
        assert loc_id is not None

    @pytest.mark.asyncio
    async def test_process_light_resolves_existing_location(
        self, client, test_user, test_pool
    ):
        """process_light resolves location_id to an existing location."""
        from schema import NarrationOutput

        game_id, service, world_gen = await _setup_game_with_world(
            client, test_user, test_pool
        )

        # Move to "Le Quart de Cycle" (exists in world)
        narration_data = _make_narration_output("Le Quart de Cycle")
        narration = NarrationOutput.model_validate(narration_data)

        result = await service.process_light(game_id, narration, current_cycle=1)
        assert result["location"] == "Le Quart de Cycle"

        # Verify the location_id is set in the games table
        async with test_pool.acquire() as conn:
            loc_id = await conn.fetchval(
                "SELECT current_location_id FROM games WHERE id = $1", game_id
            )
            loc_name = await conn.fetchval(
                "SELECT name FROM locations WHERE id = $1", loc_id
            )
        assert loc_name == "Le Quart de Cycle"

    @pytest.mark.asyncio
    async def test_process_light_npc_resolution(
        self, client, test_user, test_pool
    ):
        """process_light returns npcs_present from narration output."""
        from schema import NarrationOutput

        game_id, service, world_gen = await _setup_game_with_world(
            client, test_user, test_pool
        )

        narration_data = _make_narration_output(
            "Le Quart de Cycle", npcs_present=["Ossek"]
        )
        narration = NarrationOutput.model_validate(narration_data)

        result = await service.process_light(game_id, narration, current_cycle=1)
        assert result["npcs_present"] == ["Ossek"]

    @pytest.mark.asyncio
    async def test_process_light_clears_detail_requests_on_day_transition(
        self, client, test_user, test_pool
    ):
        """On day_transition, process_light clears detail_requests."""
        from schema import NarrationOutput

        game_id, service, world_gen = await _setup_game_with_world(
            client, test_user, test_pool
        )
        arrival_loc = world_gen.arrival_event.arrival_location_ref

        # Set some detail requests first
        await service.store_info_requests(game_id, ["Ossek", "Justine Lépicier"])

        # Verify they were stored
        async with test_pool.acquire() as conn:
            reqs = await conn.fetchval(
                "SELECT detail_requests FROM games WHERE id = $1", game_id
            )
        assert len(reqs) == 2

        # Process day transition
        narration_data = _make_day_transition_narration(arrival_loc)
        narration = NarrationOutput.model_validate(narration_data)
        await service.process_light(game_id, narration, current_cycle=1)

        # Detail requests should be cleared
        async with test_pool.acquire() as conn:
            reqs = await conn.fetchval(
                "SELECT detail_requests FROM games WHERE id = $1", game_id
            )
        assert reqs == [] or reqs == "{}"


# =============================================================================
# GAME SERVICE - apply_narrator_deltas
# =============================================================================


class TestApplyNarratorDeltas:
    """Tests for GameService.apply_narrator_deltas()"""

    @pytest.mark.asyncio
    async def test_no_deltas_returns_null_credits(self, client, test_user, test_pool):
        """When no credit/entity deltas, result has credits=None."""
        from schema import NarrationOutput

        game_id, service, world_gen = await _setup_game_with_world(
            client, test_user, test_pool
        )

        narration_data = _make_narration_output(
            world_gen.arrival_event.arrival_location_ref,

            credit_delta=None,
        )
        narration = NarrationOutput.model_validate(narration_data)

        result = await service.apply_narrator_deltas(game_id, narration, cycle=1)

        assert result["credits"] is None

    @pytest.mark.asyncio
    async def test_credit_delta_applied(self, client, test_user, test_pool):
        """Credit delta modifies protagonist balance."""
        from schema import NarrationOutput

        game_id, service, world_gen = await _setup_game_with_world(
            client, test_user, test_pool
        )

        state_before = await service.load_game_state(game_id)
        credits_before = state_before["player"]["credits"]

        narration_data = _make_narration_output(
            world_gen.arrival_event.arrival_location_ref,

            credit_delta={"amount": -25, "description": "repas au terminal"},
        )
        narration = NarrationOutput.model_validate(narration_data)

        result = await service.apply_narrator_deltas(game_id, narration, cycle=1)

        assert result["credits"]["amount"] == -25
        assert result["credits"]["new_balance"] == credits_before - 25

        state_after = await service.load_game_state(game_id)
        assert state_after["player"]["credits"] == credits_before - 25

    @pytest.mark.asyncio
    async def test_entity_reveal_marks_character_known(
        self, client, test_user, test_pool
    ):
        """entity_reveals in narration output marks a character as known."""
        from schema import NarrationOutput

        game_id, service, world_gen = await _setup_game_with_world(
            client, test_user, test_pool
        )

        # Verify Ossek is initially not known
        async with test_pool.acquire() as conn:
            known = await conn.fetchval(
                "SELECT known_by_protagonist FROM characters"
                " WHERE game_id = $1 AND name = 'Ossek'",
                game_id,
            )
        assert known is False

        narration_data = _make_narration_output(
            "Le Quart de Cycle",

            credit_delta=None,
            entity_reveals=[
                {"entity_type": "character", "current_name": "Ossek", "real_name": None}
            ],
        )
        narration = NarrationOutput.model_validate(narration_data)

        await service.apply_narrator_deltas(game_id, narration, cycle=1)

        # Verify Ossek is now known
        async with test_pool.acquire() as conn:
            known = await conn.fetchval(
                "SELECT known_by_protagonist FROM characters"
                " WHERE game_id = $1 AND name = 'Ossek'",
                game_id,
            )
        assert known is True

    @pytest.mark.asyncio
    async def test_entity_reveal_location_accessible(
        self, client, test_user, test_pool
    ):
        """Location entity_reveal marks location as accessible."""
        from schema import NarrationOutput

        game_id, service, world_gen = await _setup_game_with_world(
            client, test_user, test_pool
        )

        # Mark a location as inaccessible first
        async with test_pool.acquire() as conn:
            await conn.execute(
                "UPDATE locations SET accessible = false"
                " WHERE game_id = $1 AND name = 'Serres Hydro-7'",
                game_id,
            )

        narration_data = _make_narration_output(
            "Le Quart de Cycle",

            credit_delta=None,
            entity_reveals=[
                {"entity_type": "location", "current_name": "Serres Hydro-7"}
            ],
        )
        narration = NarrationOutput.model_validate(narration_data)

        await service.apply_narrator_deltas(game_id, narration, cycle=1)

        async with test_pool.acquire() as conn:
            accessible = await conn.fetchval(
                "SELECT accessible FROM locations"
                " WHERE game_id = $1 AND name = 'Serres Hydro-7'",
                game_id,
            )
        assert accessible is True


# =============================================================================
# GAME SERVICE - save_messages & load_chat_messages
# =============================================================================


class TestMessages:
    """Tests for save_messages and load_chat_messages."""

    @pytest.mark.asyncio
    async def test_save_and_load_messages(self, client, test_user, test_pool):
        """save_messages persists user + assistant pair, load_chat_messages retrieves them."""
        game_id, service, world_gen = await _setup_game_with_world(
            client, test_user, test_pool
        )

        user_id, assistant_id = await service.save_messages(
            game_id=game_id,
            user_message="Je regarde autour de moi",
            assistant_message="Tu observes le terminal. Rien de spécial.",
            cycle=1,
            time="09h15",
            game_date="Lundi 18 Juillet 2847",
            location_ref=world_gen.arrival_event.arrival_location_ref,
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

    @pytest.mark.asyncio
    async def test_protocol_messages_filtered(self, client, test_user, test_pool):
        """load_chat_messages filters out protocol messages like __ARRIVEE__."""
        game_id, service, world_gen = await _setup_game_with_world(
            client, test_user, test_pool
        )

        # Save a protocol message and a normal one
        await service.save_messages(
            game_id=game_id,
            user_message="__ARRIVEE__",
            assistant_message="Tu arrives sur la station...",
            cycle=1,
        )
        await service.save_messages(
            game_id=game_id,
            user_message="Bonjour",
            assistant_message="Le terminal est bruyant.",
            cycle=1,
        )

        messages = await service.load_chat_messages(game_id)

        # __ARRIVEE__ user message should be filtered, but assistant reply remains
        user_messages = [m for m in messages if m["role"] == "user"]
        assert len(user_messages) == 1
        assert user_messages[0]["content"] == "Bonjour"

        # Both assistant messages should be present
        assistant_messages = [m for m in messages if m["role"] == "assistant"]
        assert len(assistant_messages) == 2

    @pytest.mark.asyncio
    async def test_save_messages_with_narrator_deltas(
        self, client, test_user, test_pool
    ):
        """save_messages stores narrator_deltas and load_chat_messages includes cost info."""
        game_id, service, world_gen = await _setup_game_with_world(
            client, test_user, test_pool
        )

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

        await service.save_messages(
            game_id=game_id,
            user_message="Je parle à Ossek",
            assistant_message="Ossek te regarde avec mélancolie.",
            cycle=1,
            narrator_deltas=deltas,
        )

        messages = await service.load_chat_messages(game_id)
        assistant_msg = [m for m in messages if m["role"] == "assistant"][0]
        assert "cost" in assistant_msg
        assert assistant_msg["cost"]["input_tokens"] == 1000

    @pytest.mark.asyncio
    async def test_load_chat_messages_includes_roll_data(
        self, client, test_user, test_pool
    ):
        """load_chat_messages includes roll_details from mechanic_rolls join."""
        game_id, service, world_gen = await _setup_game_with_world(
            client, test_user, test_pool
        )

        _, assistant_id = await service.save_messages(
            game_id=game_id,
            user_message="Je tente d'escalader le mur",
            assistant_message="Tu grimpes avec effort.",
            cycle=1,
        )

        roll_details = {
            "dice": [-1, 0, 1, 1],
            "total": 1,
            "skill_total": 4,
            "opposition_total": None,
            "outcome": "success",
            "shifts": 2,
            "complication": False,
            "details": {"skill_name": "Athlétisme", "difficulty": 2},
        }

        await service.log_mechanic_roll(
            game_id=game_id,
            message_id=assistant_id,
            engine="fate_core",
            skill_used="Athlétisme",
            roll_details=roll_details,
            outcome="success",
            complication=False,
            cycle=1,
        )

        messages = await service.load_chat_messages(game_id)
        assistant_msg = [m for m in messages if m["role"] == "assistant"][0]
        assert "roll" in assistant_msg
        assert assistant_msg["roll"]["outcome"] == "success"
        assert assistant_msg["roll"]["dice"] == [-1, 0, 1, 1]
        assert assistant_msg["roll"]["details"]["skill_name"] == "Athlétisme"

    @pytest.mark.asyncio
    async def test_load_chat_messages_no_roll_returns_no_roll_key(
        self, client, test_user, test_pool
    ):
        """Messages without mechanic rolls should not have a 'roll' key."""
        game_id, service, world_gen = await _setup_game_with_world(
            client, test_user, test_pool
        )

        await service.save_messages(
            game_id=game_id,
            user_message="Bonjour",
            assistant_message="Bienvenue.",
            cycle=1,
        )

        messages = await service.load_chat_messages(game_id)
        for msg in messages:
            assert "roll" not in msg


# =============================================================================
# GAME SERVICE - log_mechanic_roll
# =============================================================================


class TestMechanicRolls:
    """Tests for GameService.log_mechanic_roll() and DB persistence."""

    @pytest.mark.asyncio
    async def test_log_mechanic_roll_persists_to_db(
        self, client, test_user, test_pool
    ):
        """log_mechanic_roll inserts a row in mechanic_rolls table."""
        game_id, service, world_gen = await _setup_game_with_world(
            client, test_user, test_pool
        )

        _, assistant_id = await service.save_messages(
            game_id=game_id,
            user_message="Je tire",
            assistant_message="Le blaster fait mouche.",
            cycle=1,
        )

        roll_details = {
            "dice": [3, 5, 2, 6],
            "total": 16,
            "skill_total": 19,
            "opposition_total": None,
            "outcome": "success",
            "shifts": 4,
            "complication": False,
            "details": {
                "skill_name": "Blasters",
                "dice_code": "4D",
                "difficulty": 15,
            },
        }

        await service.log_mechanic_roll(
            game_id=game_id,
            message_id=assistant_id,
            engine="d6",
            skill_used="Blasters",
            roll_details=roll_details,
            outcome="success",
            complication=False,
            cycle=1,
        )

        # Verify in DB
        async with test_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM mechanic_rolls WHERE game_id = $1", game_id
            )

        assert row is not None
        assert row["engine"] == "d6"
        assert row["skill_used"] == "Blasters"
        assert row["outcome"] == "success"
        assert row["complication"] is False
        assert row["cycle"] == 1
        assert row["message_id"] == assistant_id
        assert row["roll_details"]["dice"] == [3, 5, 2, 6]

    @pytest.mark.asyncio
    async def test_log_mechanic_roll_null_skill(
        self, client, test_user, test_pool
    ):
        """log_mechanic_roll accepts null skill_used."""
        game_id, service, world_gen = await _setup_game_with_world(
            client, test_user, test_pool
        )

        _, assistant_id = await service.save_messages(
            game_id=game_id,
            user_message="Test",
            assistant_message="Result.",
            cycle=1,
        )

        await service.log_mechanic_roll(
            game_id=game_id,
            message_id=assistant_id,
            engine="fate_core",
            skill_used=None,
            roll_details={"dice": [0, 0, 0, 0], "total": 0, "outcome": "tie"},
            outcome="tie",
            complication=False,
            cycle=1,
        )

        async with test_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM mechanic_rolls WHERE game_id = $1", game_id
            )

        assert row is not None
        assert row["skill_used"] is None
        assert row["outcome"] == "tie"

    @pytest.mark.asyncio
    async def test_log_mechanic_roll_with_complication(
        self, client, test_user, test_pool
    ):
        """log_mechanic_roll stores D6 wild die complications."""
        game_id, service, world_gen = await _setup_game_with_world(
            client, test_user, test_pool
        )

        _, assistant_id = await service.save_messages(
            game_id=game_id,
            user_message="Test",
            assistant_message="Result.",
            cycle=1,
        )

        await service.log_mechanic_roll(
            game_id=game_id,
            message_id=assistant_id,
            engine="d6",
            skill_used="Esquive",
            roll_details={
                "dice": [4, 1],
                "total": 4,
                "outcome": "failure",
                "complication": True,
                "details": {"wild_die_rolls": [1]},
            },
            outcome="failure",
            complication=True,
            cycle=2,
        )

        async with test_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM mechanic_rolls WHERE game_id = $1", game_id
            )

        assert row["complication"] is True
        assert row["cycle"] == 2

    @pytest.mark.asyncio
    async def test_multiple_rolls_across_messages(
        self, client, test_user, test_pool
    ):
        """Multiple rolls link to different assistant messages correctly."""
        game_id, service, world_gen = await _setup_game_with_world(
            client, test_user, test_pool
        )

        # Save two rounds
        _, aid1 = await service.save_messages(
            game_id=game_id,
            user_message="Action 1",
            assistant_message="Response 1",
            cycle=1,
        )
        _, aid2 = await service.save_messages(
            game_id=game_id,
            user_message="Action 2",
            assistant_message="Response 2",
            cycle=1,
        )

        await service.log_mechanic_roll(
            game_id=game_id,
            message_id=aid1,
            engine="fate_core",
            skill_used="Combat",
            roll_details={"dice": [1, 1, 0, -1], "total": 1, "outcome": "success"},
            outcome="success",
            complication=False,
            cycle=1,
        )
        await service.log_mechanic_roll(
            game_id=game_id,
            message_id=aid2,
            engine="fate_core",
            skill_used="Discrétion",
            roll_details={"dice": [-1, -1, 0, 0], "total": -2, "outcome": "failure"},
            outcome="failure",
            complication=False,
            cycle=1,
        )

        messages = await service.load_chat_messages(game_id)
        assistants = [m for m in messages if m["role"] == "assistant"]
        assert len(assistants) == 2

        # Each assistant message has its own roll
        assert assistants[0]["roll"]["dice"] == [1, 1, 0, -1]
        assert assistants[0]["roll"]["outcome"] == "success"
        assert assistants[1]["roll"]["dice"] == [-1, -1, 0, 0]
        assert assistants[1]["roll"]["outcome"] == "failure"

    @pytest.mark.asyncio
    async def test_log_mechanic_roll_returns_uuid(
        self, client, test_user, test_pool
    ):
        """log_mechanic_roll returns the UUID of the inserted row."""
        game_id, service, world_gen = await _setup_game_with_world(
            client, test_user, test_pool
        )
        roll_id = await service.log_mechanic_roll(
            game_id=game_id,
            message_id=None,
            engine="fate_core",
            skill_used="Combat",
            roll_details={"dice": [0, 0, 0, 0], "total": 0},
            outcome="failure",
            complication=False,
            cycle=1,
        )
        assert roll_id is not None
        assert isinstance(roll_id, UUID)

    @pytest.mark.asyncio
    async def test_load_pending_roll(
        self, client, test_user, test_pool
    ):
        """load_pending_roll retrieves a roll with no message_id."""
        game_id, service, world_gen = await _setup_game_with_world(
            client, test_user, test_pool
        )
        roll_details = {
            "dice": [-1, 0, 0, -1],
            "total": -2,
            "skill_total": 1,
            "outcome": "failure",
            "shifts": -3,
            "details": {"skill_name": "Combat", "difficulty": 4},
        }
        roll_id = await service.log_mechanic_roll(
            game_id=game_id,
            message_id=None,
            engine="fate_core",
            skill_used="Combat",
            roll_details=roll_details,
            outcome="failure",
            complication=False,
            cycle=1,
        )

        pending = await service.load_pending_roll(game_id, roll_id)
        assert pending is not None
        assert pending["id"] == roll_id
        assert pending["outcome"] == "failure"
        assert pending["roll_details"]["skill_total"] == 1

    @pytest.mark.asyncio
    async def test_load_pending_roll_not_found_after_link(
        self, client, test_user, test_pool
    ):
        """load_pending_roll returns None once message_id is set."""
        game_id, service, world_gen = await _setup_game_with_world(
            client, test_user, test_pool
        )
        roll_id = await service.log_mechanic_roll(
            game_id=game_id,
            message_id=None,
            engine="fate_core",
            skill_used="Combat",
            roll_details={"dice": [0], "total": 0},
            outcome="failure",
            complication=False,
            cycle=1,
        )

        # Save a message and link the roll
        _, aid = await service.save_messages(
            game_id=game_id,
            user_message="test",
            assistant_message="response",
            cycle=1,
        )
        await service.update_mechanic_roll(
            roll_id, {"dice": [0], "total": 0}, "tie", message_id=aid
        )

        # Now pending search should return None (message_id is no longer NULL)
        pending = await service.load_pending_roll(game_id, roll_id)
        assert pending is None

    @pytest.mark.asyncio
    async def test_update_mechanic_roll(
        self, client, test_user, test_pool
    ):
        """update_mechanic_roll updates outcome and details."""
        game_id, service, world_gen = await _setup_game_with_world(
            client, test_user, test_pool
        )
        original = {"dice": [-1, 0, 0, -1], "total": -2, "outcome": "failure"}
        roll_id = await service.log_mechanic_roll(
            game_id=game_id,
            message_id=None,
            engine="fate_core",
            skill_used="Combat",
            roll_details=original,
            outcome="failure",
            complication=False,
            cycle=1,
        )

        # Simulate invocation: update to success
        updated = {**original, "outcome": "success", "details": {"invoked_aspects": ["A"]}}
        await service.update_mechanic_roll(roll_id, updated, "success")

        # Verify via pending load (still no message_id)
        pending = await service.load_pending_roll(game_id, roll_id)
        assert pending["outcome"] == "success"
        assert pending["roll_details"]["details"]["invoked_aspects"] == ["A"]


# =============================================================================
# GAME SERVICE - rollback_to_message
# =============================================================================


class TestRollback:
    """Tests for GameService.rollback_to_message()"""

    @pytest.mark.asyncio
    async def test_rollback_deletes_messages(self, client, test_user, test_pool):
        """rollback_to_message removes messages from the given index onward."""
        from schema import NarrationOutput

        game_id, service, world_gen = await _setup_game_with_world(
            client, test_user, test_pool
        )
        arrival_loc = world_gen.arrival_event.arrival_location_ref

        # Save 3 rounds of messages
        for i in range(3):
            narration_data = _make_narration_output(arrival_loc)
            narration = NarrationOutput.model_validate(narration_data)
            await service.process_light(game_id, narration, current_cycle=1)
            await service.save_messages(
                game_id=game_id,
                user_message=f"Action {i + 1}",
                assistant_message=f"Response {i + 1}",
                cycle=1,
                time="09h15",
                location_ref=arrival_loc,
                game_date="Lundi 18 Juillet 2847",
            )

        messages_before = await service.load_chat_messages(game_id)
        assert len(messages_before) == 6  # 3 rounds * 2 messages

        # Rollback from index 2 (keep first round only)
        result = await service.rollback_to_message(game_id, keep_until_index=2)
        assert result["deleted"] == 4
        assert result["target_cycle"] == 1

        messages_after = await service.load_chat_messages(game_id)
        assert len(messages_after) == 2

    @pytest.mark.asyncio
    async def test_rollback_restores_game_state(self, client, test_user, test_pool):
        """rollback restores game_date, time, and location from last remaining message."""
        from schema import NarrationOutput

        game_id, service, world_gen = await _setup_game_with_world(
            client, test_user, test_pool
        )
        arrival_loc = world_gen.arrival_event.arrival_location_ref

        # First round: save with time/date/location
        narration_data = _make_narration_output(arrival_loc)
        narration = NarrationOutput.model_validate(narration_data)
        await service.process_light(game_id, narration, current_cycle=1)
        await service.save_messages(
            game_id=game_id,
            user_message="Premier tour",
            assistant_message="Première réponse",
            cycle=1,
            time="09h15",
            game_date="Lundi 18 Juillet 2847",
            location_ref=arrival_loc,
        )

        # Second round: different time/location
        narration_data2 = _make_narration_output(
            "Le Quart de Cycle",
            time={"new_time": "10h30", "ellipse": False},
        )
        narration2 = NarrationOutput.model_validate(narration_data2)
        await service.process_light(game_id, narration2, current_cycle=1)
        await service.save_messages(
            game_id=game_id,
            user_message="Deuxième tour",
            assistant_message="Deuxième réponse",
            cycle=1,
            time="10h30",
            game_date="Lundi 18 Juillet 2847",
            location_ref="Le Quart de Cycle",
        )

        # Rollback to first round
        result = await service.rollback_to_message(game_id, keep_until_index=2)
        assert result["deleted"] == 2

        # Verify game state was restored
        async with test_pool.acquire() as conn:
            game = await conn.fetchrow(
                'SELECT current_cycle, "current_date", "current_time" FROM games WHERE id = $1',
                game_id,
            )
        assert game["current_cycle"] == 1
        assert game["current_time"] == "09h15"
        assert game["current_date"] == "Lundi 18 Juillet 2847"

    @pytest.mark.asyncio
    async def test_rollback_beyond_messages_noop(self, client, test_user, test_pool):
        """Rollback with index >= message count returns deleted=0."""
        game_id, service, world_gen = await _setup_game_with_world(
            client, test_user, test_pool
        )

        result = await service.rollback_to_message(game_id, keep_until_index=999)
        assert result["deleted"] == 0


# =============================================================================
# GAME SERVICE - load_game_state & load_world_info
# =============================================================================


class TestGameStateLoading:
    """Tests for load_game_state and load_world_info."""

    @pytest.mark.asyncio
    async def test_load_game_state_after_world_creation(
        self, client, test_user, test_pool
    ):
        """load_game_state returns a complete state dict after world population."""
        game_id, service, world_gen = await _setup_game_with_world(
            client, test_user, test_pool
        )

        state = await service.load_game_state(game_id)

        assert state["world_created"] is True
        assert state["game"]["name"] is not None
        assert state["game"]["current_cycle"] >= 1
        assert state["game"]["game_date"] is not None
        assert "player" in state
        assert "credits" in state["player"]
        assert "inventory" in state["player"]

    @pytest.mark.asyncio
    async def test_load_game_state_before_world_creation(
        self, client, test_user, test_pool
    ):
        """load_game_state on a newly created game (no world) raises ValueError."""
        from services.game_service import GameService

        resp = await client.post(
            "/api/games", headers=auth_headers(test_user["token"])
        )
        game_id = UUID(resp.json()["gameId"])
        service = GameService(test_pool)

        # Before world creation, world_created should be false
        # but game should still load (no protagonist means default stats)
        state = await service.load_game_state(game_id)
        assert state["world_created"] is False

    @pytest.mark.asyncio
    async def test_load_world_info_after_population(
        self, client, test_user, test_pool
    ):
        """load_world_info returns structured world summary."""
        game_id, service, world_gen = await _setup_game_with_world(
            client, test_user, test_pool
        )

        world_info = await service.load_world_info(game_id)

        assert world_info is not None
        assert world_info["world"]["name"] == "Escale Méridienne"
        assert world_info["npc_count"] >= 3
        assert world_info["location_count"] >= 4
        assert world_info["ai"]["name"] == "Célimène"
        assert world_info["protagonist"]["name"] == "Valentin"

    @pytest.mark.asyncio
    async def test_load_world_info_before_population(
        self, client, test_user, test_pool
    ):
        """load_world_info returns None if world not created."""
        from services.game_service import GameService

        resp = await client.post(
            "/api/games", headers=auth_headers(test_user["token"])
        )
        game_id = UUID(resp.json()["gameId"])
        service = GameService(test_pool)

        result = await service.load_world_info(game_id)
        assert result is None


# =============================================================================
# GAME SERVICE - verify_ownership
# =============================================================================


class TestVerifyOwnership:
    """Tests for GameService.verify_ownership()"""

    @pytest.mark.asyncio
    async def test_authorized_access(self, client, test_user, test_pool):
        """verify_ownership passes for the correct owner."""
        from services.game_service import GameService

        resp = await client.post(
            "/api/games", headers=auth_headers(test_user["token"])
        )
        game_id = UUID(resp.json()["gameId"])
        service = GameService(test_pool)

        # Should not raise — test_user["id"] is already a UUID from asyncpg
        user_id = UUID(str(test_user["id"]))
        await service.verify_ownership(game_id, user_id)

    @pytest.mark.asyncio
    async def test_unauthorized_access(
        self, client, test_user, second_user, test_pool
    ):
        """verify_ownership raises 403 for a different user."""
        from fastapi import HTTPException
        from services.game_service import GameService

        resp = await client.post(
            "/api/games", headers=auth_headers(test_user["token"])
        )
        game_id = UUID(resp.json()["gameId"])
        service = GameService(test_pool)

        other_id = UUID(str(second_user["id"]))
        with pytest.raises(HTTPException) as exc_info:
            await service.verify_ownership(game_id, other_id)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_nonexistent_game(self, client, test_user, test_pool):
        """verify_ownership raises 404 for a non-existent game."""
        from uuid import uuid4

        from fastapi import HTTPException
        from services.game_service import GameService

        service = GameService(test_pool)

        user_id = UUID(str(test_user["id"]))
        with pytest.raises(HTTPException) as exc_info:
            await service.verify_ownership(uuid4(), user_id)
        assert exc_info.value.status_code == 404


# =============================================================================
# GAME SERVICE - store_info_requests
# =============================================================================


class TestStoreInfoRequests:
    """Tests for GameService.store_info_requests()"""

    @pytest.mark.asyncio
    async def test_store_and_retrieve_info_requests(
        self, client, test_user, test_pool
    ):
        """store_info_requests persists entity names for next turn."""
        from services.game_service import GameService

        resp = await client.post(
            "/api/games", headers=auth_headers(test_user["token"])
        )
        game_id = UUID(resp.json()["gameId"])
        service = GameService(test_pool)

        await service.store_info_requests(
            game_id, ["Ossek", "Justine Lépicier"]
        )

        async with test_pool.acquire() as conn:
            reqs = await conn.fetchval(
                "SELECT detail_requests FROM games WHERE id = $1", game_id
            )
        assert "Ossek" in reqs
        assert "Justine Lépicier" in reqs


# =============================================================================
# GAME SERVICE - build_llm_messages
# =============================================================================


class TestBuildLLMMessages:
    """Tests for GameService.build_llm_messages()"""

    @pytest.mark.asyncio
    async def test_build_llm_messages_with_history(
        self, client, test_user, test_pool
    ):
        """build_llm_messages builds correct message array with history."""
        game_id, service, world_gen = await _setup_game_with_world(
            client, test_user, test_pool
        )
        arrival_loc = world_gen.arrival_event.arrival_location_ref

        # Save two rounds of messages
        times = ["09h15", "09h45"]
        for i in range(2):
            await service.save_messages(
                game_id=game_id,
                user_message=f"Action {i + 1}",
                assistant_message=f"Response {i + 1}",
                cycle=1,
                time=times[i],
                location_ref=arrival_loc,
            )

        context = "Tu es dans le terminal. Que fais-tu ?"
        messages = await service.build_llm_messages(
            game_id, current_cycle=1, context_prompt=context
        )

        # Should have: history messages + final context prompt
        assert len(messages) >= 3
        assert messages[-1]["role"] == "user"
        assert messages[-1]["content"] == context

    @pytest.mark.asyncio
    async def test_build_llm_messages_empty_history(
        self, client, test_user, test_pool
    ):
        """build_llm_messages with no prior messages returns only the context prompt."""
        game_id, service, world_gen = await _setup_game_with_world(
            client, test_user, test_pool
        )

        context = "Tu arrives sur la station."
        messages = await service.build_llm_messages(
            game_id, current_cycle=1, context_prompt=context
        )

        assert len(messages) == 1
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == context


# =============================================================================
# GAME SERVICE - _extract_arc_suffix (static helper)
# =============================================================================


class TestExtractArcSuffix:
    """Tests for the static _extract_arc_suffix helper."""

    def test_with_arc_advanced(self):
        """Returns arc progression suffix."""
        from services.game_service import GameService

        deltas = {"hints": {"arc_advanced": ["La mère malade"]}}
        result = GameService._extract_arc_suffix(deltas)
        assert "La mère malade" in result
        assert "↑" in result

    def test_with_arc_resolved(self):
        """Returns arc resolved suffix."""
        from services.game_service import GameService

        deltas = {"hints": {"arc_resolved": ["Burnout silencieux"]}}
        result = GameService._extract_arc_suffix(deltas)
        assert "Burnout silencieux" in result

    def test_with_no_hints(self):
        """Returns None when no arc info."""
        from services.game_service import GameService

        result = GameService._extract_arc_suffix(None)
        assert result is None

    def test_with_string_json(self):
        """Handles narrator_deltas stored as JSON string."""
        from services.game_service import GameService

        deltas_str = json.dumps({"hints": {"arc_advanced": ["Test Arc"]}})
        result = GameService._extract_arc_suffix(deltas_str)
        assert "Test Arc" in result

    def test_with_empty_hints(self):
        """Returns None when hints exist but are empty."""
        from services.game_service import GameService

        deltas = {"hints": {}}
        result = GameService._extract_arc_suffix(deltas)
        assert result is None


# =============================================================================
# EXTRACTION POPULATOR - process_extraction
# =============================================================================


class TestExtractionPopulator:
    """Tests for ExtractionPopulator.process_extraction()"""

    @pytest.mark.asyncio
    async def test_process_extraction_with_facts(
        self, client, test_user, test_pool
    ):
        """process_extraction creates facts in the DB."""
        from kg.specialized_populator import ExtractionPopulator
        from schema import NarrativeExtraction

        game_id, service, world_gen = await _setup_game_with_world(
            client, test_user, test_pool
        )

        extraction = NarrativeExtraction.model_validate({
            "cycle": 2,
            "time": "10h20",
            "current_location_ref": "Le Quart de Cycle",
            "facts": [
                {
                    "cycle": 2,
                    "fact_type": "revelation",
                    "description": "Ossek révèle qu'iel est seul de son espèce sur la station",
                    "semantic_key": "ossek:revele:seul_espece",
                    "importance": 4,
                    "participants": [
                        {"entity_ref": "Ossek", "role": "actor"},
                        {"entity_ref": "Valentin", "role": "witness"},
                    ],
                }
            ],
            "segment_summary": "Valentin discute avec Ossek au Quart de Cycle.",
            "key_npcs_present": ["Ossek"],
        })

        populator = ExtractionPopulator(test_pool, game_id)
        stats = await populator.process_extraction(extraction)

        assert stats["facts_created"] == 1
        assert stats["errors"] == []

        # Verify fact in DB
        async with test_pool.acquire() as conn:
            fact_count = await conn.fetchval(
                "SELECT count(*) FROM facts"
                " WHERE game_id = $1 AND semantic_key = 'ossek:revele:seul_espece'",
                game_id,
            )
        assert fact_count == 1

    @pytest.mark.asyncio
    async def test_process_extraction_creates_entity(
        self, client, test_user, test_pool
    ):
        """process_extraction creates a new character entity."""
        from kg.specialized_populator import ExtractionPopulator
        from schema import NarrativeExtraction

        game_id, service, world_gen = await _setup_game_with_world(
            client, test_user, test_pool
        )

        extraction = NarrativeExtraction.model_validate({
            "cycle": 2,
            "entities_created": [
                {
                    "entity_type": "character",
                    "name": "Elena Vasquez",
                    "known_by_protagonist": True,
                    "data": {
                        "description": "Grande, cheveux courts noirs",
                        "species": "human",
                        "gender": "femme",
                        "occupation": "ingénieure réseau",
                        "mood": "anxieuse",
                    },
                }
            ],
        })

        populator = ExtractionPopulator(test_pool, game_id)
        stats = await populator.process_extraction(extraction)

        assert stats["entities_created"] == 1

        # Verify character in DB
        async with test_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT name, occupation, known_by_protagonist FROM characters"
                " WHERE game_id = $1 AND name = 'Elena Vasquez'",
                game_id,
            )
        assert row is not None
        assert row["occupation"] == "ingénieure réseau"
        assert row["known_by_protagonist"] is True

    @pytest.mark.asyncio
    async def test_process_extraction_creates_location(
        self, client, test_user, test_pool
    ):
        """process_extraction creates a new location entity."""
        from kg.specialized_populator import ExtractionPopulator
        from schema import NarrativeExtraction

        game_id, service, world_gen = await _setup_game_with_world(
            client, test_user, test_pool
        )

        extraction = NarrativeExtraction.model_validate({
            "cycle": 2,
            "entities_created": [
                {
                    "entity_type": "location",
                    "name": "Marché Noir Section 9",
                    "data": {
                        "location_type": "market",
                        "sector": "Quartier Ouvrier",
                        "description": "Un couloir sombre où des stands improvisés vendent de tout.",
                        "atmosphere": "tendue et animée",
                    },
                }
            ],
        })

        populator = ExtractionPopulator(test_pool, game_id)
        stats = await populator.process_extraction(extraction)

        assert stats["entities_created"] == 1

        async with test_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT name, location_type, sector FROM locations"
                " WHERE game_id = $1 AND name = 'Marché Noir Section 9'",
                game_id,
            )
        assert row is not None
        assert row["location_type"] == "market"
        assert row["sector"] == "Quartier Ouvrier"

    @pytest.mark.asyncio
    async def test_process_extraction_creates_organization(
        self, client, test_user, test_pool
    ):
        """process_extraction creates a new organization entity."""
        from kg.specialized_populator import ExtractionPopulator
        from schema import NarrativeExtraction

        game_id, service, world_gen = await _setup_game_with_world(
            client, test_user, test_pool
        )

        extraction = NarrativeExtraction.model_validate({
            "cycle": 2,
            "entities_created": [
                {
                    "entity_type": "organization",
                    "name": "Syndicat des Dockers",
                    "data": {
                        "org_type": "union",
                        "domain": "transport",
                        "description": "Syndicat influent qui contrôle le quai central.",
                    },
                }
            ],
        })

        populator = ExtractionPopulator(test_pool, game_id)
        stats = await populator.process_extraction(extraction)

        assert stats["entities_created"] == 1

        async with test_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT name, org_type, domain FROM organizations"
                " WHERE game_id = $1 AND name = 'Syndicat des Dockers'",
                game_id,
            )
        assert row is not None
        assert row["org_type"] == "union"

    @pytest.mark.asyncio
    async def test_process_extraction_creates_object(
        self, client, test_user, test_pool
    ):
        """process_extraction creates a new object via entities_created and adds to inventory."""
        from kg.specialized_populator import ExtractionPopulator
        from schema import NarrativeExtraction

        game_id, service, world_gen = await _setup_game_with_world(
            client, test_user, test_pool
        )

        extraction = NarrativeExtraction.model_validate({
            "cycle": 2,
            "entities_created": [
                {
                    "entity_type": "object",
                    "name": "Clé magnétique usagée",
                    "data": {
                        "category": "tech",
                        "description": "Clé de service trouvée dans un couloir",
                        "transportable": True,
                        "base_value": 10,
                    },
                }
            ],
        })

        populator = ExtractionPopulator(test_pool, game_id)
        stats = await populator.process_extraction(extraction)

        assert stats["entities_created"] == 1

        async with test_pool.acquire() as conn:
            obj = await conn.fetchrow(
                "SELECT name, category FROM objects"
                " WHERE game_id = $1 AND name = 'Clé magnétique usagée'",
                game_id,
            )
            # Object should also be in inventory
            inv = await conn.fetchval(
                """SELECT count(*) FROM inventory i
                   JOIN objects o ON i.object_id = o.id
                   WHERE i.game_id = $1 AND o.name = 'Clé magnétique usagée'""",
                game_id,
            )
        assert obj is not None
        assert inv == 1

    @pytest.mark.asyncio
    async def test_process_extraction_objects_created(
        self, client, test_user, test_pool
    ):
        """process_extraction handles objects_created (acquisition path)."""
        from kg.specialized_populator import ExtractionPopulator
        from schema import NarrativeExtraction

        game_id, service, world_gen = await _setup_game_with_world(
            client, test_user, test_pool
        )

        extraction = NarrativeExtraction.model_validate({
            "cycle": 2,
            "objects_created": [
                {
                    "name": "Carte d'accès niveau 2",
                    "category": "tech",
                    "description": "Carte magnétique bleue avec puce intégrée",
                    "transportable": True,
                    "stackable": False,
                    "base_value": 50,
                    "quantity": 1,
                    "from_hint": "Carte d'accès temporaire",
                }
            ],
        })

        populator = ExtractionPopulator(test_pool, game_id)
        stats = await populator.process_extraction(extraction)

        assert stats["objects_created"] == 1

        async with test_pool.acquire() as conn:
            obj = await conn.fetchrow(
                "SELECT name, category, base_value FROM objects"
                " WHERE game_id = $1 AND name = $2",
                game_id,
                "Carte d'accès niveau 2",
            )
            inv_qty = await conn.fetchval(
                """SELECT i.quantity FROM inventory i
                   JOIN objects o ON i.object_id = o.id
                   WHERE i.game_id = $1 AND o.name = $2""",
                game_id,
                "Carte d'accès niveau 2",
            )
        assert obj is not None
        assert obj["base_value"] == 50
        assert inv_qty == 1

    @pytest.mark.asyncio
    async def test_process_extraction_updates_entity(
        self, client, test_user, test_pool
    ):
        """process_extraction updates an existing entity's fields."""
        from kg.specialized_populator import ExtractionPopulator
        from schema import NarrativeExtraction

        game_id, service, world_gen = await _setup_game_with_world(
            client, test_user, test_pool
        )

        # Check initial mood
        async with test_pool.acquire() as conn:
            initial_mood = await conn.fetchval(
                "SELECT mood FROM characters"
                " WHERE game_id = $1 AND name = 'Ossek'",
                game_id,
            )

        extraction = NarrativeExtraction.model_validate({
            "cycle": 2,
            "entities_updated": [
                {
                    "entity_ref": "Ossek",
                    "entity_type": "character",
                    "changes": {"mood": "plus détendu, presque souriant"},
                }
            ],
        })

        populator = ExtractionPopulator(test_pool, game_id)
        stats = await populator.process_extraction(extraction)

        assert stats["entities_updated"] == 1

        async with test_pool.acquire() as conn:
            new_mood = await conn.fetchval(
                "SELECT mood FROM characters"
                " WHERE game_id = $1 AND name = 'Ossek'",
                game_id,
            )
        assert new_mood == "plus détendu, presque souriant"
        assert new_mood != initial_mood

    @pytest.mark.asyncio
    async def test_process_extraction_creates_relation(
        self, client, test_user, test_pool
    ):
        """process_extraction creates a new relation between entities."""
        from kg.specialized_populator import ExtractionPopulator
        from schema import NarrativeExtraction

        game_id, service, world_gen = await _setup_game_with_world(
            client, test_user, test_pool
        )

        extraction = NarrativeExtraction.model_validate({
            "cycle": 2,
            "relations_created": [
                {
                    "cycle": 2,
                    "relation": {
                        "source_ref": "Valentin",
                        "target_ref": "Ossek",
                        "relation_type": "knows",
                        "known_by_protagonist": True,
                        "level": 2,
                        "context": "Rencontre au Quart de Cycle",
                    },
                }
            ],
        })

        populator = ExtractionPopulator(test_pool, game_id)
        stats = await populator.process_extraction(extraction)

        assert stats["relations_created"] == 1

        # Verify relation in DB
        async with test_pool.acquire() as conn:
            rel = await conn.fetchrow(
                """SELECT r.level, r.context, r.type
                   FROM relations r
                   JOIN entity_registry src ON r.source_id = src.id
                   JOIN entity_registry tgt ON r.target_id = tgt.id
                   WHERE r.game_id = $1
                     AND LOWER(src.name) = 'valentin'
                     AND LOWER(tgt.name) = 'ossek'
                     AND r.type = 'knows'
                     AND r.end_cycle IS NULL""",
                game_id,
            )
        assert rel is not None
        assert rel["level"] == 2

    @pytest.mark.asyncio
    async def test_process_extraction_creates_arc(
        self, client, test_user, test_pool
    ):
        """process_extraction creates a new narrative arc."""
        from kg.specialized_populator import ExtractionPopulator
        from schema import NarrativeExtraction

        game_id, service, world_gen = await _setup_game_with_world(
            client, test_user, test_pool
        )

        extraction = NarrativeExtraction.model_validate({
            "cycle": 2,
            "arcs_created": [
                {
                    "title": "Les rumeurs de rachat",
                    "domain": "professional",
                    "description": "Des rumeurs circulent sur un investisseur externe intéressé par Symbiose Tech.",
                    "involved_entities": ["Symbiose Tech"],
                    "intensity": 3,
                }
            ],
        })

        populator = ExtractionPopulator(test_pool, game_id)
        stats = await populator.process_extraction(extraction)

        assert stats["arcs_created"] == 1

        async with test_pool.acquire() as conn:
            arc = await conn.fetchrow(
                "SELECT title, domain, intensity, resolved FROM narrative_arcs"
                " WHERE game_id = $1 AND title = 'Les rumeurs de rachat'",
                game_id,
            )
        assert arc is not None
        assert arc["domain"] == "professional"
        assert arc["intensity"] == 3
        assert arc["resolved"] is False

    @pytest.mark.asyncio
    async def test_process_extraction_schedules_event(
        self, client, test_user, test_pool
    ):
        """process_extraction schedules a future event."""
        from kg.specialized_populator import ExtractionPopulator
        from schema import NarrativeExtraction

        game_id, service, world_gen = await _setup_game_with_world(
            client, test_user, test_pool
        )

        extraction = NarrativeExtraction.model_validate({
            "cycle": 2,
            "events_scheduled": [
                {
                    "event_type": "appointment",
                    "title": "Déjeuner avec Ossek",
                    "description": "RDV informel au Quart de Cycle",
                    "planned_cycle": 5,
                    "time": "12h30",
                    "location_ref": "Le Quart de Cycle",
                    "participants": ["Ossek"],
                }
            ],
        })

        populator = ExtractionPopulator(test_pool, game_id)
        stats = await populator.process_extraction(extraction)

        # Verify event in DB
        async with test_pool.acquire() as conn:
            event = await conn.fetchrow(
                "SELECT title, planned_cycle, time FROM events"
                " WHERE game_id = $1 AND title = 'Déjeuner avec Ossek'",
                game_id,
            )
        assert event is not None
        assert event["planned_cycle"] == 5
        assert event["time"] == "12h30"

    @pytest.mark.asyncio
    async def test_process_extraction_credit_transactions(
        self, client, test_user, test_pool
    ):
        """process_extraction applies credit transactions."""
        from kg.specialized_populator import ExtractionPopulator
        from schema import NarrativeExtraction

        game_id, service, world_gen = await _setup_game_with_world(
            client, test_user, test_pool
        )

        state_before = await service.load_game_state(game_id)
        credits_before = state_before["player"]["credits"]

        extraction = NarrativeExtraction.model_validate({
            "cycle": 2,
            "credit_transactions": [
                {"amount": -50, "description": "Réparation du terminal"},
                {"amount": 200, "description": "Prime de bienvenue"},
            ],
        })

        populator = ExtractionPopulator(test_pool, game_id)
        stats = await populator.process_extraction(extraction)

        assert stats["credits_changed"] == 2

        state_after = await service.load_game_state(game_id)
        assert state_after["player"]["credits"] == credits_before - 50 + 200

    @pytest.mark.asyncio
    async def test_process_extraction_chronology_saved(
        self, client, test_user, test_pool
    ):
        """process_extraction saves a chronology entry from segment_summary."""
        from kg.specialized_populator import ExtractionPopulator
        from schema import NarrativeExtraction

        game_id, service, world_gen = await _setup_game_with_world(
            client, test_user, test_pool
        )

        extraction = NarrativeExtraction.model_validate({
            "cycle": 2,
            "time": "10h20",
            "current_location_ref": "Le Quart de Cycle",
            "segment_summary": "Valentin commande un café au Quart de Cycle et discute brièvement avec Ossek.",
            "key_npcs_present": ["Ossek"],
        })

        populator = ExtractionPopulator(test_pool, game_id)
        await populator.process_extraction(extraction)

        # Verify chronology entry
        async with test_pool.acquire() as conn:
            chrono = await conn.fetchrow(
                "SELECT cycle, summary FROM chronology"
                " WHERE game_id = $1 AND cycle = 2",
                game_id,
            )
        assert chrono is not None
        assert "café" in chrono["summary"].lower()

    @pytest.mark.asyncio
    async def test_process_extraction_full_pipeline(
        self, client, test_user, test_pool
    ):
        """Full extraction: facts + entity creation + relation + arc + event + credits."""
        from kg.specialized_populator import ExtractionPopulator
        from schema import NarrativeExtraction

        game_id, service, world_gen = await _setup_game_with_world(
            client, test_user, test_pool
        )

        extraction_data = {
            "cycle": 2,
            "time": "10h20",
            "current_location_ref": "Le Quart de Cycle",
            "facts": [
                {
                    "cycle": 2,
                    "fact_type": "action",
                    "description": "Valentin commande un café au Quart de Cycle",
                    "semantic_key": "valentin:commande:cafe",
                    "importance": 2,
                    "participants": [
                        {"entity_ref": "Valentin", "role": "actor"},
                    ],
                },
                {
                    "cycle": 2,
                    "fact_type": "revelation",
                    "description": "Ossek mentionne que Justine vient souvent le soir",
                    "semantic_key": "ossek:mentionne:justine_soir",
                    "importance": 3,
                    "participants": [
                        {"entity_ref": "Ossek", "role": "actor"},
                        {"entity_ref": "Valentin", "role": "witness"},
                    ],
                },
            ],
            "entities_created": [
                {
                    "entity_type": "character",
                    "name": "Marco Diaz",
                    "known_by_protagonist": True,
                    "data": {
                        "description": "Petit, nerveux, toujours en mouvement",
                        "species": "human",
                        "gender": "homme",
                        "occupation": "coursier",
                    },
                }
            ],
            "relations_created": [
                {
                    "cycle": 2,
                    "relation": {
                        "source_ref": "Valentin",
                        "target_ref": "Ossek",
                        "relation_type": "knows",
                        "known_by_protagonist": True,
                        "level": 2,
                        "context": "Client régulier du café",
                    },
                }
            ],
            "arcs_created": [
                {
                    "title": "Le mystère du coursier",
                    "domain": "personal",
                    "description": "Marco semble transporter des colis suspects.",
                    "involved_entities": ["Marco Diaz"],
                    "intensity": 2,
                }
            ],
            "credit_transactions": [
                {"amount": -8, "description": "Café au Quart de Cycle"},
            ],
            "events_scheduled": [
                {
                    "event_type": "appointment",
                    "title": "Marco revient demain matin",
                    "planned_cycle": 3,
                    "time": "08h00",
                    "location_ref": "Le Quart de Cycle",
                    "participants": ["Marco Diaz"],
                }
            ],
            "segment_summary": "Valentin prend un café et fait connaissance avec Ossek et Marco.",
            "key_npcs_present": ["Ossek", "Marco Diaz"],
        }

        extraction = NarrativeExtraction.model_validate(extraction_data)
        populator = ExtractionPopulator(test_pool, game_id)
        stats = await populator.process_extraction(extraction)

        assert stats["facts_created"] == 2
        assert stats["entities_created"] == 1
        assert stats["relations_created"] == 1
        assert stats["arcs_created"] == 1
        assert stats["credits_changed"] == 1
        assert stats["errors"] == []

    @pytest.mark.asyncio
    async def test_process_extraction_entity_update_detects_type(
        self, client, test_user, test_pool
    ):
        """process_extraction detects entity type from registry when not provided."""
        from kg.specialized_populator import ExtractionPopulator
        from schema import NarrativeExtraction

        game_id, service, world_gen = await _setup_game_with_world(
            client, test_user, test_pool
        )

        # Update Ossek without specifying entity_type -- populator should detect 'character'
        extraction = NarrativeExtraction.model_validate({
            "cycle": 2,
            "entities_updated": [
                {
                    "entity_ref": "Ossek",
                    "changes": {"mood": "curieux et attentif"},
                }
            ],
        })

        populator = ExtractionPopulator(test_pool, game_id)
        stats = await populator.process_extraction(extraction)

        assert stats["entities_updated"] == 1

        async with test_pool.acquire() as conn:
            mood = await conn.fetchval(
                "SELECT mood FROM characters"
                " WHERE game_id = $1 AND name = 'Ossek'",
                game_id,
            )
        assert mood == "curieux et attentif"

    @pytest.mark.asyncio
    async def test_process_extraction_arc_update(
        self, client, test_user, test_pool
    ):
        """process_extraction updates an existing arc's progress and intensity."""
        from kg.specialized_populator import ExtractionPopulator
        from schema import NarrativeExtraction

        game_id, service, world_gen = await _setup_game_with_world(
            client, test_user, test_pool
        )

        # "La mère malade" is created during world gen
        extraction = NarrativeExtraction.model_validate({
            "cycle": 2,
            "arcs_updated": [
                {
                    "arc_title": "La mère malade",
                    "intensity": 4,
                    "progress": 15,
                    "situation": "Justine mentionne des frais médicaux en hausse",
                }
            ],
        })

        populator = ExtractionPopulator(test_pool, game_id)
        stats = await populator.process_extraction(extraction)

        assert stats.get("arcs_updated", 0) == 1

        async with test_pool.acquire() as conn:
            arc = await conn.fetchrow(
                "SELECT intensity, progress, situation FROM narrative_arcs"
                " WHERE game_id = $1 AND LOWER(title) = LOWER('La mère malade')"
                " AND resolved = false",
                game_id,
            )
        assert arc is not None
        assert arc["intensity"] == 4
        assert arc["progress"] == 15

    @pytest.mark.asyncio
    async def test_process_extraction_arc_resolved(
        self, client, test_user, test_pool
    ):
        """process_extraction resolves an existing arc."""
        from kg.specialized_populator import ExtractionPopulator
        from schema import NarrativeExtraction

        game_id, service, world_gen = await _setup_game_with_world(
            client, test_user, test_pool
        )

        extraction = NarrativeExtraction.model_validate({
            "cycle": 5,
            "arcs_resolved": [
                {
                    "arc_title": "Le mal du banc",
                    "resolution": "Ossek trouve un équilibre grâce à la relation avec Valentin",
                }
            ],
        })

        populator = ExtractionPopulator(test_pool, game_id)
        await populator.process_extraction(extraction)

        async with test_pool.acquire() as conn:
            arc = await conn.fetchrow(
                "SELECT resolved, resolved_cycle, resolution FROM narrative_arcs"
                " WHERE game_id = $1 AND LOWER(title) = LOWER('Le mal du banc')",
                game_id,
            )
        assert arc is not None
        assert arc["resolved"] is True
        assert arc["resolved_cycle"] == 5

    @pytest.mark.asyncio
    async def test_process_extraction_inventory_lose(
        self, client, test_user, test_pool
    ):
        """process_extraction handles inventory 'lose' action."""
        from kg.specialized_populator import ExtractionPopulator
        from schema import NarrativeExtraction

        game_id, service, world_gen = await _setup_game_with_world(
            client, test_user, test_pool
        )

        # "Terminal personnel" should be in inventory from world gen
        async with test_pool.acquire() as conn:
            inv_before = await conn.fetchval(
                """SELECT i.quantity FROM inventory i
                   JOIN objects o ON i.object_id = o.id
                   WHERE i.game_id = $1 AND o.name = 'Terminal personnel'""",
                game_id,
            )
        assert inv_before is not None

        extraction = NarrativeExtraction.model_validate({
            "cycle": 2,
            "inventory_changes": [
                {
                    "action": "lose",
                    "object_ref": "Terminal personnel",
                    "quantity_delta": 1,
                    "reason": "Volé dans le terminal",
                }
            ],
        })

        populator = ExtractionPopulator(test_pool, game_id)
        await populator.process_extraction(extraction)

        async with test_pool.acquire() as conn:
            inv_after = await conn.fetchval(
                """SELECT i.quantity FROM inventory i
                   JOIN objects o ON i.object_id = o.id
                   WHERE i.game_id = $1 AND o.name = 'Terminal personnel'""",
                game_id,
            )
        # Quantity should have decreased or the row deleted
        assert inv_after is None or inv_after < inv_before

    @pytest.mark.asyncio
    async def test_process_extraction_inventory_use(
        self, client, test_user, test_pool
    ):
        """process_extraction handles inventory 'use' action by creating a fact."""
        from kg.specialized_populator import ExtractionPopulator
        from schema import NarrativeExtraction

        game_id, service, world_gen = await _setup_game_with_world(
            client, test_user, test_pool
        )

        extraction = NarrativeExtraction.model_validate({
            "cycle": 2,
            "inventory_changes": [
                {
                    "action": "use",
                    "object_ref": "Terminal personnel",
                    "quantity_delta": 1,
                    "reason": "Consulter les messages",
                }
            ],
        })

        populator = ExtractionPopulator(test_pool, game_id)
        await populator.process_extraction(extraction)

        # 'use' creates an ACTION fact
        async with test_pool.acquire() as conn:
            fact = await conn.fetchrow(
                "SELECT description FROM facts"
                " WHERE game_id = $1 AND semantic_key LIKE 'valentin:use:%'",
                game_id,
            )
        assert fact is not None
        assert "Terminal personnel" in fact["description"]

    @pytest.mark.asyncio
    async def test_process_extraction_ambient_update(
        self, client, test_user, test_pool
    ):
        """process_extraction updates ambient field on an entity."""
        from kg.specialized_populator import ExtractionPopulator
        from schema import NarrativeExtraction

        game_id, service, world_gen = await _setup_game_with_world(
            client, test_user, test_pool
        )

        extraction = NarrativeExtraction.model_validate({
            "cycle": 2,
            "ambient_updates": [
                {
                    "entity_ref": "Le Quart de Cycle",
                    "entity_type": "location",
                    "ambient": "L'endroit semble plus animé ce soir, une musique douce filtre depuis l'arrière-salle.",
                }
            ],
        })

        populator = ExtractionPopulator(test_pool, game_id)
        stats = await populator.process_extraction(extraction)

        assert stats.get("ambients_updated", 0) == 1

        async with test_pool.acquire() as conn:
            ambient = await conn.fetchval(
                "SELECT ambient FROM locations"
                " WHERE game_id = $1 AND name = 'Le Quart de Cycle'",
                game_id,
            )
        assert ambient is not None
        assert "animé" in ambient

    @pytest.mark.asyncio
    async def test_process_extraction_entity_reveal_via_update(
        self, client, test_user, test_pool
    ):
        """process_extraction handles entity update with now_known=True (identity reveal)."""
        from kg.specialized_populator import ExtractionPopulator
        from schema import NarrativeExtraction

        game_id, service, world_gen = await _setup_game_with_world(
            client, test_user, test_pool
        )

        # Verify Justine is not known initially
        async with test_pool.acquire() as conn:
            known = await conn.fetchval(
                "SELECT known_by_protagonist FROM characters"
                " WHERE game_id = $1 AND name = 'Justine Lépicier'",
                game_id,
            )
        assert known is False

        extraction = NarrativeExtraction.model_validate({
            "cycle": 2,
            "entities_updated": [
                {
                    "entity_ref": "Justine Lépicier",
                    "entity_type": "character",
                    "now_known": True,
                    "changes": {"mood": "souriante et détendue"},
                }
            ],
        })

        populator = ExtractionPopulator(test_pool, game_id)
        await populator.process_extraction(extraction)

        async with test_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT known_by_protagonist, mood FROM characters"
                " WHERE game_id = $1 AND name = 'Justine Lépicier'",
                game_id,
            )
        assert row["known_by_protagonist"] is True
        assert row["mood"] == "souriante et détendue"

    @pytest.mark.asyncio
    async def test_process_extraction_skips_owns_relations(
        self, client, test_user, test_pool
    ):
        """process_extraction skips OWNS relation type (handled by inventory)."""
        from kg.specialized_populator import ExtractionPopulator
        from schema import NarrativeExtraction

        game_id, service, world_gen = await _setup_game_with_world(
            client, test_user, test_pool
        )

        extraction = NarrativeExtraction.model_validate({
            "cycle": 2,
            "relations_created": [
                {
                    "cycle": 2,
                    "relation": {
                        "source_ref": "Valentin",
                        "target_ref": "Terminal personnel",
                        "relation_type": "owns",
                        "known_by_protagonist": True,
                    },
                }
            ],
        })

        populator = ExtractionPopulator(test_pool, game_id)
        stats = await populator.process_extraction(extraction)

        # OWNS should be skipped
        assert stats["relations_created"] == 0


# =============================================================================
# GAME SERVICE — load_npcs / load_locations / load_organizations / load_quests
# =============================================================================


class TestGameServiceLoadSidebar:
    """Tests for sidebar data loading (load_npcs, load_locations, etc.)."""

    @pytest.mark.asyncio
    async def test_load_npcs_returns_list_of_dicts(
        self, client, test_user, test_pool
    ):
        """load_npcs returns properly typed list after world population."""
        game_id, service, world_gen = await _setup_game_with_world(
            client, test_user, test_pool
        )

        npcs = await service.load_npcs(game_id)
        assert isinstance(npcs, list)
        assert len(npcs) > 0

        for npc in npcs:
            assert isinstance(npc, dict)
            assert "id" in npc
            assert "name" in npc
            assert isinstance(npc["name"], str)
            assert len(npc["name"]) > 0
            # relationship should be a label string, not None
            assert npc["relationship"] in (
                "Inconnu", "Hostile", "Neutre", "Connaissance", "Ami", "Ami proche"
            )

    @pytest.mark.asyncio
    async def test_load_locations_returns_list_of_dicts(
        self, client, test_user, test_pool
    ):
        """load_locations returns properly typed list after world population."""
        game_id, service, world_gen = await _setup_game_with_world(
            client, test_user, test_pool
        )

        locations = await service.load_locations(game_id)
        assert isinstance(locations, list)
        assert len(locations) > 0

        for loc in locations:
            assert isinstance(loc, dict)
            assert "id" in loc
            assert "name" in loc
            assert isinstance(loc["name"], str)
            assert isinstance(loc.get("accessible", True), bool)

    @pytest.mark.asyncio
    async def test_load_organizations_returns_list_of_dicts(
        self, client, test_user, test_pool
    ):
        """load_organizations returns properly typed list after world population."""
        game_id, service, world_gen = await _setup_game_with_world(
            client, test_user, test_pool
        )

        orgs = await service.load_organizations(game_id)
        assert isinstance(orgs, list)
        assert len(orgs) > 0

        for org in orgs:
            assert isinstance(org, dict)
            assert "id" in org
            assert "name" in org
            assert isinstance(org["name"], str)

    @pytest.mark.asyncio
    async def test_load_quests_returns_list_of_dicts(
        self, client, test_user, test_pool
    ):
        """load_quests returns properly typed list with correct fields."""
        game_id, service, world_gen = await _setup_game_with_world(
            client, test_user, test_pool
        )

        quests = await service.load_quests(game_id)
        assert isinstance(quests, list)
        # World gen example should have some arcs
        assert len(quests) > 0

        for quest in quests:
            assert isinstance(quest, dict)
            assert "id" in quest
            assert "name" in quest
            assert isinstance(quest["name"], str)
            assert quest["type"] in (
                "personal", "professional", "social", "mystery",
                "health", "family", "financial", "community",
            ) or isinstance(quest["type"], str)
            assert quest["status"] == "En cours"

    @pytest.mark.asyncio
    async def test_load_npcs_empty_game(self, client, test_user, test_pool):
        """load_npcs on a game with no world returns empty list."""
        from services.game_service import GameService

        resp = await client.post("/api/games", headers=auth_headers(test_user["token"]))
        game_id = UUID(resp.json()["gameId"])

        service = GameService(test_pool)
        npcs = await service.load_npcs(game_id)
        assert npcs == []


# =============================================================================
# CONTEXT BUILDER — _build_* methods
# =============================================================================


class TestContextBuilderMethods:
    """Tests for ContextBuilder internal methods (DB round-trip)."""

    @pytest.mark.asyncio
    async def test_build_produces_valid_narration_context(
        self, client, test_user, test_pool
    ):
        """Full build() produces a valid NarrationContext after world population."""
        from services.context_builder import ContextBuilder
        from schema.narration import NarrationContext

        game_id, service, world_gen = await _setup_game_with_world(
            client, test_user, test_pool
        )

        builder = ContextBuilder(test_pool, game_id)
        async with test_pool.acquire() as conn:
            # Get initial location from world gen
            location_name = world_gen.locations[0].name
            ctx = await builder.build(
                conn,
                player_input="Je regarde autour de moi",
                current_cycle=1,
                current_time="08h00",
                current_location_name=location_name,
            )

        assert isinstance(ctx, NarrationContext)
        assert ctx.current_cycle == 1
        assert ctx.protagonist.name == world_gen.protagonist.name
        assert len(ctx.all_npcs) > 0
        assert isinstance(ctx.organizations, list)
        assert isinstance(ctx.active_arcs, list)
        assert isinstance(ctx.facts, list)
        assert isinstance(ctx.director_planned_events, list)

    @pytest.mark.asyncio
    async def test_build_events_returns_typed_list(
        self, client, test_user, test_pool
    ):
        """_build_events returns list of EventSummary from DB."""
        from services.context_builder import ContextBuilder
        from kg.populator import KnowledgeGraphPopulator

        game_id, service, world_gen = await _setup_game_with_world(
            client, test_user, test_pool
        )

        # Create an event in the DB
        populator = KnowledgeGraphPopulator(test_pool, game_id)
        async with test_pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO events (game_id, title, type, planned_cycle, created_cycle)
                   VALUES ($1, 'Réunion urgente', 'appointment', 2, 1)""",
                game_id,
            )

        builder = ContextBuilder(test_pool, game_id)
        async with test_pool.acquire() as conn:
            events = await builder._build_events(conn, current_cycle=1)

        assert isinstance(events, list)
        # Should find our event (planned for cycle 2, we're at cycle 1)
        titles = [e.title for e in events]
        assert "Réunion urgente" in titles

    @pytest.mark.asyncio
    async def test_build_facts_returns_typed_list(
        self, client, test_user, test_pool
    ):
        """_build_facts returns list of Fact from DB."""
        from services.context_builder import ContextBuilder

        game_id, service, world_gen = await _setup_game_with_world(
            client, test_user, test_pool
        )

        builder = ContextBuilder(test_pool, game_id)
        async with test_pool.acquire() as conn:
            facts = await builder._build_facts(conn, current_cycle=1)

        assert isinstance(facts, list)
        # World gen creates initial facts (arrival)
        assert len(facts) > 0
        for f in facts:
            assert isinstance(f.cycle, int)
            assert isinstance(f.description, str)
            assert isinstance(f.importance, int)
            assert isinstance(f.involves, list)

    @pytest.mark.asyncio
    async def test_build_cycle_summaries_returns_typed_list(
        self, client, test_user, test_pool
    ):
        """_build_cycle_summaries returns list of CycleSummary."""
        from services.context_builder import ContextBuilder

        game_id, service, world_gen = await _setup_game_with_world(
            client, test_user, test_pool
        )

        builder = ContextBuilder(test_pool, game_id)
        async with test_pool.acquire() as conn:
            summaries = await builder._build_cycle_summaries(conn, current_cycle=10)

        # At cycle 1, no summaries yet — just verify it returns a list
        assert isinstance(summaries, list)

    @pytest.mark.asyncio
    async def test_build_companion_returns_correct_type(
        self, client, test_user, test_pool
    ):
        """_build_companion returns CompanionSummary with correct fields."""
        from services.context_builder import ContextBuilder
        from schema.narration import CompanionSummary

        game_id, service, world_gen = await _setup_game_with_world(
            client, test_user, test_pool
        )

        builder = ContextBuilder(test_pool, game_id)
        async with test_pool.acquire() as conn:
            companion = await builder._build_companion(conn)

        assert companion is not None
        assert isinstance(companion, CompanionSummary)
        assert companion.name == world_gen.companion.name
        assert isinstance(companion.personality_traits, list)

    @pytest.mark.asyncio
    async def test_build_connected_locations_returns_list(
        self, client, test_user, test_pool
    ):
        """_build_connected_locations returns list of LocationSummary."""
        from services.context_builder import ContextBuilder

        game_id, service, world_gen = await _setup_game_with_world(
            client, test_user, test_pool
        )

        location_name = world_gen.locations[0].name
        builder = ContextBuilder(test_pool, game_id)
        async with test_pool.acquire() as conn:
            connected = await builder._build_connected_locations(conn, location_name)

        assert isinstance(connected, list)
        # All entries should be LocationSummary-like
        for loc in connected:
            assert hasattr(loc, "name")
            assert hasattr(loc, "type")

    @pytest.mark.asyncio
    async def test_build_requested_details_empty_default(
        self, client, test_user, test_pool
    ):
        """_build_requested_details returns empty dict when no requests."""
        from services.context_builder import ContextBuilder

        game_id, service, world_gen = await _setup_game_with_world(
            client, test_user, test_pool
        )

        builder = ContextBuilder(test_pool, game_id)
        async with test_pool.acquire() as conn:
            details = await builder._build_requested_details(conn)

        assert isinstance(details, dict)
        assert len(details) == 0

    @pytest.mark.asyncio
    async def test_build_requested_details_with_requests(
        self, client, test_user, test_pool
    ):
        """_build_requested_details returns entity data for stored requests."""
        from services.context_builder import ContextBuilder

        game_id, service, world_gen = await _setup_game_with_world(
            client, test_user, test_pool
        )

        # Store a detail request for a known entity
        npc_name = world_gen.characters[0].name
        await service.store_info_requests(game_id, [npc_name])

        builder = ContextBuilder(test_pool, game_id)
        async with test_pool.acquire() as conn:
            details = await builder._build_requested_details(conn)

        assert isinstance(details, dict)
        assert npc_name in details
        assert isinstance(details[npc_name], dict)

    @pytest.mark.asyncio
    async def test_active_arcs_from_context_builder(
        self, client, test_user, test_pool
    ):
        """_build_active_arcs returns ActiveArcSummary objects from DB data."""
        from services.context_builder import ContextBuilder
        from schema.narration import ActiveArcSummary

        game_id, service, world_gen = await _setup_game_with_world(
            client, test_user, test_pool
        )

        builder = ContextBuilder(test_pool, game_id)
        async with test_pool.acquire() as conn:
            arcs_rows = await builder.reader.get_active_arcs(conn)
            active_arcs = builder._build_active_arcs(arcs_rows)

        assert isinstance(active_arcs, list)
        assert len(active_arcs) > 0
        for arc in active_arcs:
            assert isinstance(arc, ActiveArcSummary)
            assert isinstance(arc.type, str)
            assert isinstance(arc.title, str)
            assert isinstance(arc.description_brief, str)
            assert isinstance(arc.involved, list)


# =============================================================================
# CONTEXT BUILDER — _row_to_npc_summary traits string fallback
# =============================================================================


class TestContextBuilderTraitsFallback:
    """Test that _row_to_npc_summary handles traits as string (JSONB edge case)."""

    def test_traits_as_list(self):
        """Normal case: traits is already a list."""
        from services.context_builder import ContextBuilder

        builder = ContextBuilder.__new__(ContextBuilder)
        row = {
            "name": "Elena",
            "known_by_protagonist": True,
            "occupation": "ingénieure",
            "species": "human",
            "traits": ["prudente", "loyale", "curieuse"],
            "relation_context": "collègue",
            "relation_level": 5,
            "usual_location": "Labo",
            "ambient": None,
        }
        npc = builder._row_to_npc_summary(row)
        assert npc.traits == ["prudente", "loyale", "curieuse"]

    def test_traits_as_json_string(self):
        """Edge case: traits stored as JSON string instead of list."""
        from services.context_builder import ContextBuilder

        builder = ContextBuilder.__new__(ContextBuilder)
        row = {
            "name": "Raj",
            "known_by_protagonist": True,
            "occupation": "médecin",
            "species": "human",
            "traits": '["calme", "méthodique"]',
            "relation_context": None,
            "relation_level": 3,
            "usual_location": "Infirmerie",
            "ambient": None,
        }
        npc = builder._row_to_npc_summary(row)
        assert isinstance(npc.traits, list)
        assert npc.traits == ["calme", "méthodique"]

    def test_traits_as_invalid_string(self):
        """Edge case: traits is a non-JSON string."""
        from services.context_builder import ContextBuilder

        builder = ContextBuilder.__new__(ContextBuilder)
        row = {
            "name": "Zed",
            "known_by_protagonist": True,
            "occupation": None,
            "species": "alien",
            "traits": "not valid json",
            "relation_context": None,
            "relation_level": None,
            "usual_location": None,
            "ambient": None,
        }
        npc = builder._row_to_npc_summary(row)
        assert npc.traits == []

    def test_traits_none(self):
        """Edge case: traits is None."""
        from services.context_builder import ContextBuilder

        builder = ContextBuilder.__new__(ContextBuilder)
        row = {
            "name": "Ghost",
            "known_by_protagonist": False,
            "unknown_name": "Silhouette",
            "occupation": None,
            "species": "human",
            "traits": None,
            "relation_context": None,
            "relation_level": None,
            "usual_location": None,
            "ambient": None,
        }
        npc = builder._row_to_npc_summary(row)
        assert npc.traits == []
        assert npc.name == "Silhouette"


# =============================================================================
# GAME SERVICE — update_mechanic_roll JSONB round-trip
# =============================================================================


class TestMechanicRollJsonbRoundTrip:
    """Verify mechanic roll details survive DB round-trip as correct types."""

    @pytest.mark.asyncio
    async def test_roll_details_round_trip(self, client, test_user, test_pool):
        """Roll details stored via json.dumps + ::jsonb should read back as dict."""
        from schema import NarrationOutput

        game_id, service, world_gen = await _setup_game_with_world(
            client, test_user, test_pool
        )

        # Log a mechanic roll
        roll_details = {
            "dice": [3, 5],
            "total": 8,
            "skill": "Combat",
            "difficulty": 6,
            "shifts": 2,
        }
        roll_id = await service.log_mechanic_roll(
            game_id=game_id,
            message_id=None,
            engine="fate_core",
            skill_used="Combat",
            roll_details=roll_details,
            outcome="success",
            complication=False,
            cycle=1,
        )

        # Load it back
        pending = await service.load_pending_roll(game_id, roll_id)
        assert pending is not None
        assert isinstance(pending["roll_details"], dict)
        assert pending["roll_details"]["total"] == 8
        assert pending["roll_details"]["dice"] == [3, 5]

    @pytest.mark.asyncio
    async def test_update_roll_details_round_trip(self, client, test_user, test_pool):
        """Updated roll details should also round-trip correctly."""
        game_id, service, world_gen = await _setup_game_with_world(
            client, test_user, test_pool
        )

        roll_id = await service.log_mechanic_roll(
            game_id=game_id,
            message_id=None,
            engine="fate_core",
            skill_used="Empathie",
            roll_details={"dice": [1, 2], "total": 3},
            outcome="tie",
            complication=False,
            cycle=1,
        )

        # Update with aspect invocation
        new_details = {
            "dice": [1, 2],
            "total": 5,
            "aspect_invoked": "Ancien soldat",
            "bonus": 2,
        }
        await service.update_mechanic_roll(roll_id, new_details, "success")

        # Verify round-trip via direct DB read
        async with test_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT roll_details, outcome FROM mechanic_rolls WHERE id = $1",
                roll_id,
            )
        assert isinstance(row["roll_details"], dict)
        assert row["roll_details"]["aspect_invoked"] == "Ancien soldat"
        assert row["outcome"] == "success"


# =============================================================================
# EXTRACTION ORCHESTRATOR — concurrent guard and phase execution
# =============================================================================


class TestExtractionOrchestratorIntegration:
    """Integration tests for the extraction orchestrator."""

    @pytest.mark.asyncio
    async def test_orchestrator_with_no_triggers(self, client, test_user, test_pool):
        """Orchestrator with no triggers runs resolver only."""
        from services.extraction.orchestrator import run_resolve_and_extract

        game_id, service, world_gen = await _setup_game_with_world(
            client, test_user, test_pool
        )

        result = await run_resolve_and_extract(
            pool=test_pool,
            game_id=game_id,
            trigger_cycle=1,
            triggers=[],
            message_content="Le soleil se couche.",
        )

        assert isinstance(result, dict)
        assert "extractors" in result
        assert len(result["extractors"]) == 0

    @pytest.mark.asyncio
    async def test_orchestrator_concurrent_guard(self, client, test_user, test_pool):
        """Concurrent extraction for same game is rejected."""
        from services.extraction.orchestrator import (
            run_resolve_and_extract,
            _extracting_games,
        )

        game_id, service, world_gen = await _setup_game_with_world(
            client, test_user, test_pool
        )

        # Simulate an in-progress extraction
        key = str(game_id)
        _extracting_games.add(key)
        try:
            result = await run_resolve_and_extract(
                pool=test_pool,
                game_id=game_id,
                trigger_cycle=1,
                triggers=["characters"],
                message_content="Test",
            )
            assert result.get("skipped") is True
            assert result.get("reason") == "concurrent"
        finally:
            _extracting_games.discard(key)

    @pytest.mark.asyncio
    async def test_orchestrator_guard_cleared_after_run(
        self, client, test_user, test_pool
    ):
        """Guard is cleared even when orchestrator completes (no lingering lock)."""
        from services.extraction.orchestrator import (
            run_resolve_and_extract,
            _extracting_games,
        )

        game_id, service, world_gen = await _setup_game_with_world(
            client, test_user, test_pool
        )

        key = str(game_id)
        assert key not in _extracting_games

        await run_resolve_and_extract(
            pool=test_pool,
            game_id=game_id,
            trigger_cycle=1,
            triggers=[],
        )

        assert key not in _extracting_games
