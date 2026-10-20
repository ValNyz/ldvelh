"""
Integration tests for GameService and the extractors' knowledge-graph writes.
Uses the real test database — no LLM calls (mocked data).

Covers:
  - GameService: rollback_to_message, load_chat_messages, load_game_state,
    load_world_info, verify_ownership, build_llm_messages
    (turn writes are set up through repos.turns, tested in test_repos_turns.py)
  - Extractor writes (by entity id): facts, entities, relations, events, objects,
    inventory, ambient updates, reveals
"""

import json
import uuid
from uuid import UUID

import pytest

from unittest.mock import MagicMock

from helpers import (
    apply_deltas,
    apply_state,
    auth_headers,
    message_id_at,
    open_turn,
    save_pair,
    store_requests,
)
from repos import turns
from repos.uow import uow
from services.identity.service import IdentityService
from domain.identity import EntityRef
from tests.prompt_examples import WORLD_GENERATION_EXAMPLE

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
            turn = await open_turn(test_pool, game_id)
            await apply_state(test_pool, game_id, narration, 1, turn_id=turn)
            await save_pair(
                test_pool,
                game_id=game_id,
                user_message=f"Action {i + 1}",
                assistant_message=f"Response {i + 1}",
                cycle=1,
                time="09h15",
                location_ref=arrival_loc,
                game_date="Lundi 18 Juillet 2847",
                turn_id=turn,
            )

        messages_before = await service.load_chat_messages(game_id)
        assert len(messages_before) == 6  # 3 rounds * 2 messages

        # Rollback from index 2 (keep first round only)
        result = await service.rollback_to_message(game_id, message_id=await message_id_at(test_pool, game_id, 2))
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
        turn = await open_turn(test_pool, game_id)
        await apply_state(test_pool, game_id, narration, 1, turn_id=turn)
        await save_pair(
            test_pool,
            game_id=game_id,
            user_message="Premier tour",
            assistant_message="Première réponse",
            cycle=1,
            time="09h15",
            game_date="Lundi 18 Juillet 2847",
            location_ref=arrival_loc,
            turn_id=turn,
        )

        # Second round: different time/location
        narration_data2 = _make_narration_output(
            "Le Quart de Cycle",
            time={"new_time": "10h30", "ellipse": False},
        )
        narration2 = NarrationOutput.model_validate(narration_data2)
        turn = await open_turn(test_pool, game_id)
        await apply_state(test_pool, game_id, narration2, 1, turn_id=turn)
        await save_pair(
            test_pool,
            game_id=game_id,
            user_message="Deuxième tour",
            assistant_message="Deuxième réponse",
            cycle=1,
            time="10h30",
            game_date="Lundi 18 Juillet 2847",
            location_ref="Le Quart de Cycle",
            turn_id=turn,
        )

        # Rollback to first round
        result = await service.rollback_to_message(game_id, message_id=await message_id_at(test_pool, game_id, 2))
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
        """Rollback with an unknown message id returns deleted=0."""
        game_id, service, world_gen = await _setup_game_with_world(
            client, test_user, test_pool
        )

        result = await service.rollback_to_message(game_id, message_id=uuid.uuid4())
        assert result["deleted"] == 0

    @pytest.mark.asyncio
    async def test_rollback_reverses_credits(self, client, test_user, test_pool):
        """Rollback reverses credit changes from deleted messages."""
        from schema import NarrationOutput

        game_id, service, world_gen = await _setup_game_with_world(
            client, test_user, test_pool
        )
        arrival_loc = world_gen.arrival_event.arrival_location_ref

        # Get initial credit balance
        reader = service._get_reader(game_id)
        async with test_pool.acquire() as conn:
            stats = await reader.get_protagonist_stats(conn)
        initial_credits = stats["credits"]

        # Round 1: spend 50 credits
        narration1 = NarrationOutput.model_validate(
            _make_narration_output(
                arrival_loc,
                credit_delta={"amount": -50, "description": "achat"},
            )
        )
        turn = await open_turn(test_pool, game_id)
        await apply_state(test_pool, game_id, narration1, 1, turn_id=turn)
        await apply_deltas(test_pool, game_id, narration1, 1, turn_id=turn)
        await save_pair(
            test_pool,
            game_id,
            "action1",
            "response1",
            cycle=1,
            time="09h15",
            location_ref=arrival_loc,
            narrator_deltas={"credit_delta": {"amount": -50, "description": "achat"}},
            turn_id=turn,
        )

        # Round 2: spend 30 credits
        narration2 = NarrationOutput.model_validate(
            _make_narration_output(
                arrival_loc,
                credit_delta={"amount": -30, "description": "repas"},
            )
        )
        turn = await open_turn(test_pool, game_id)
        await apply_state(test_pool, game_id, narration2, 1, turn_id=turn)
        await apply_deltas(test_pool, game_id, narration2, 1, turn_id=turn)
        await save_pair(
            test_pool,
            game_id,
            "action2",
            "response2",
            cycle=1,
            time="10h00",
            location_ref=arrival_loc,
            narrator_deltas={"credit_delta": {"amount": -30, "description": "repas"}},
            turn_id=turn,
        )

        # Verify credits went down by 80 total
        async with test_pool.acquire() as conn:
            stats = await reader.get_protagonist_stats(conn)
        assert stats["credits"] == initial_credits - 80

        # Rollback: keep only first round (index 2 = keep messages 0,1)
        await service.rollback_to_message(game_id, message_id=await message_id_at(test_pool, game_id, 2))

        # Credits from round 2 (-30) should be reversed
        async with test_pool.acquire() as conn:
            stats = await reader.get_protagonist_stats(conn)
        assert stats["credits"] == initial_credits - 50

    @pytest.mark.asyncio
    async def test_rollback_cleans_inventory(self, client, test_user, test_pool):
        """Rollback removes inventory items acquired after rollback point."""
        from schema import NarrationOutput

        game_id, service, world_gen = await _setup_game_with_world(
            client, test_user, test_pool
        )
        arrival_loc = world_gen.arrival_event.arrival_location_ref

        # Save messages at cycle 1 and cycle 2
        for cycle in [1, 2]:
            narration = NarrationOutput.model_validate(
                _make_narration_output(arrival_loc)
            )
            turn = await open_turn(test_pool, game_id)
            await apply_state(test_pool, game_id, narration, cycle, turn_id=turn)
            await save_pair(
                test_pool,
                game_id,
                f"action{cycle}",
                f"response{cycle}",
                cycle=cycle,
                time="09h00",
                location_ref=arrival_loc,
                turn_id=turn,
            )

        # Create an object and add to inventory at cycle 2
        async with test_pool.acquire() as conn, uow(conn, turn):  # under the last turn
            obj_id = await conn.fetchval(
                "INSERT INTO objects (game_id, name, created_cycle)"
                " VALUES ($1, 'Épée rouillée', 2) RETURNING id",
                game_id,
            )
            await conn.execute(
                "INSERT INTO inventory (game_id, object_id, acquired_cycle)"
                " VALUES ($1, $2, 2)",
                game_id,
                obj_id,
            )
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM inventory"
                " WHERE game_id = $1 AND acquired_cycle = 2",
                game_id,
            )
            assert count == 1

        # Rollback to keep cycle 1 messages (2 msgs), remove cycle 2+ data
        await service.rollback_to_message(game_id, message_id=await message_id_at(test_pool, game_id, 2))

        async with test_pool.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM inventory"
                " WHERE game_id = $1 AND acquired_cycle > 1",
                game_id,
            )
        assert count == 0

    @pytest.mark.asyncio
    async def test_rollback_preserves_message_order(self, client, test_user, test_pool):
        """After rollback, remaining messages are in correct sequence order."""
        from schema import NarrationOutput

        game_id, service, world_gen = await _setup_game_with_world(
            client, test_user, test_pool
        )
        arrival_loc = world_gen.arrival_event.arrival_location_ref

        # Send 3 rounds with different cycles
        times = ["09h00", "10h00", "11h00"]
        for i, cycle in enumerate([1, 2, 3]):
            narration = NarrationOutput.model_validate(
                _make_narration_output(
                    arrival_loc,
                    time={"new_time": times[i], "ellipse": False},
                )
            )
            turn = await open_turn(test_pool, game_id)
            await apply_state(test_pool, game_id, narration, cycle, turn_id=turn)
            await save_pair(
                test_pool,
                game_id,
                f"Action cycle {cycle}",
                f"Response cycle {cycle}",
                cycle=cycle,
                time=times[i],
                location_ref=arrival_loc,
                turn_id=turn,
            )

        # Rollback to keep only first 2 rounds (4 messages)
        await service.rollback_to_message(game_id, message_id=await message_id_at(test_pool, game_id, 4))

        messages = await service.load_chat_messages(game_id)
        assert len(messages) == 4

        # Verify order: user1, assistant1, user2, assistant2
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "Action cycle 1"
        assert messages[1]["role"] == "assistant"
        assert messages[1]["content"] == "Response cycle 1"
        assert messages[2]["role"] == "user"
        assert messages[2]["content"] == "Action cycle 2"
        assert messages[3]["role"] == "assistant"
        assert messages[3]["content"] == "Response cycle 2"

        # Verify cycles are monotonic
        cycles = [m["cycle"] for m in messages if m.get("cycle")]
        for i in range(1, len(cycles)):
            assert cycles[i] >= cycles[i - 1], f"Messages not in cycle order: {cycles}"

    @pytest.mark.asyncio
    async def test_rollback_then_new_messages_ordered(
        self, client, test_user, test_pool
    ):
        """After rollback, new messages are correctly ordered after remaining ones."""
        from schema import NarrationOutput

        game_id, service, world_gen = await _setup_game_with_world(
            client, test_user, test_pool
        )
        arrival_loc = world_gen.arrival_event.arrival_location_ref

        # Send 2 rounds
        for cycle in [1, 2]:
            narration = NarrationOutput.model_validate(
                _make_narration_output(arrival_loc)
            )
            turn = await open_turn(test_pool, game_id)
            await apply_state(test_pool, game_id, narration, cycle, turn_id=turn)
            await save_pair(
                test_pool,
                game_id,
                f"Action {cycle}",
                f"Response {cycle}",
                cycle=cycle,
                time="09h00",
                location_ref=arrival_loc,
                turn_id=turn,
            )

        # Rollback to keep first round only
        await service.rollback_to_message(game_id, message_id=await message_id_at(test_pool, game_id, 2))

        # Send a new message after rollback
        narration = NarrationOutput.model_validate(_make_narration_output(arrival_loc))
        turn = await open_turn(test_pool, game_id)
        await apply_state(test_pool, game_id, narration, 1, turn_id=turn)
        await save_pair(
            test_pool,
            game_id,
            "New action after rollback",
            "New response after rollback",
            cycle=1,
            time="09h30",
            location_ref=arrival_loc,
            turn_id=turn,
        )

        messages = await service.load_chat_messages(game_id)
        assert len(messages) == 4

        # Original round 1 + new round should be in sequence
        assert messages[0]["content"] == "Action 1"
        assert messages[1]["content"] == "Response 1"
        assert messages[2]["content"] == "New action after rollback"
        assert messages[3]["content"] == "New response after rollback"

    @pytest.mark.asyncio
    async def test_rollback_cleans_director_plans(self, client, test_user, test_pool):
        """Rollback removes director plans from rolled-back cycles."""
        from schema import NarrationOutput

        game_id, service, world_gen = await _setup_game_with_world(
            client, test_user, test_pool
        )
        arrival_loc = world_gen.arrival_event.arrival_location_ref

        # Save messages at cycle 1 and cycle 2
        for cycle in [1, 2]:
            narration = NarrationOutput.model_validate(
                _make_narration_output(arrival_loc)
            )
            turn = await open_turn(test_pool, game_id)
            await apply_state(test_pool, game_id, narration, cycle, turn_id=turn)
            await save_pair(
                test_pool,
                game_id,
                f"action{cycle}",
                f"response{cycle}",
                cycle=cycle,
                time="09h00",
                location_ref=arrival_loc,
                turn_id=turn,
            )

        # Insert a director plan at cycle 3
        async with test_pool.acquire() as conn, uow(conn, turn):  # under the last turn
            await conn.execute(
                """INSERT INTO director_plans
                   (game_id, cycle, ig_time, tension_level, narrator_guidance)
                   VALUES ($1, 3, '14h00', 4, 'test guidance')""",
                game_id,
            )
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM director_plans WHERE game_id = $1",
                game_id,
            )
            assert count >= 1

        # Rollback to keep cycle 1 messages (2 msgs), remove cycle 2+ data
        await service.rollback_to_message(game_id, message_id=await message_id_at(test_pool, game_id, 2))

        async with test_pool.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM director_plans WHERE game_id = $1 AND cycle > 1",
                game_id,
            )
        assert count == 0

    @pytest.mark.asyncio
    async def test_rollback_by_message_id(self, client, test_user, test_pool):
        """rollback_to_message with message_id deletes correct messages."""
        from schema import NarrationOutput

        game_id, service, world_gen = await _setup_game_with_world(
            client, test_user, test_pool
        )
        arrival_loc = world_gen.arrival_event.arrival_location_ref

        # Save 2 rounds
        for i in range(2):
            narration = NarrationOutput.model_validate(
                _make_narration_output(arrival_loc)
            )
            turn = await open_turn(test_pool, game_id)
            await apply_state(test_pool, game_id, narration, 1, turn_id=turn)
            await save_pair(
                test_pool,
                game_id,
                f"Action {i + 1}",
                f"Response {i + 1}",
                cycle=1,
                time="09h15",
                location_ref=arrival_loc,
                turn_id=turn,
            )

        messages = await service.load_chat_messages(game_id)
        assert len(messages) == 4

        # Rollback by ID of the 3rd message (user message of round 2)
        from uuid import UUID as _UUID

        target_id = _UUID(messages[2]["id"])
        result = await service.rollback_to_message(game_id, message_id=target_id)

        assert result["deleted"] == 2  # messages[2] and messages[3]
        remaining = await service.load_chat_messages(game_id)
        assert len(remaining) == 2
        assert remaining[0]["content"] == "Action 1"
        assert remaining[1]["content"] == "Response 1"

    @pytest.mark.asyncio
    async def test_rollback_by_id_with_protocol_messages(
        self, client, test_user, test_pool
    ):
        """Message ID rollback works even when protocol messages exist in DB."""
        from schema import NarrationOutput

        game_id, service, world_gen = await _setup_game_with_world(
            client, test_user, test_pool
        )
        arrival_loc = world_gen.arrival_event.arrival_location_ref

        # Save a protocol message (hidden from frontend)
        async with test_pool.acquire() as conn:
            conv_id = await turns.active_conversation(conn, game_id)
            if not conv_id:
                conv_id = await turns.create_conversation(conn, game_id, 1)
            await turns.save_message(
                conn,
                game_id,
                conv_id,
                "user",
                "__ARRIVEE__",
                sequence=1,
                cycle=1,
            )

        # Save 2 visible rounds
        for i in range(2):
            narration = NarrationOutput.model_validate(
                _make_narration_output(arrival_loc)
            )
            turn = await open_turn(test_pool, game_id)
            await apply_state(test_pool, game_id, narration, 1, turn_id=turn)
            await save_pair(
                test_pool,
                game_id,
                f"Action {i + 1}",
                f"Response {i + 1}",
                cycle=1,
                time="09h15",
                location_ref=arrival_loc,
                turn_id=turn,
            )

        # Frontend sees 4 messages (protocol filtered out)
        visible = await service.load_chat_messages(game_id)
        assert len(visible) == 4

        # Rollback by ID of 3rd visible message (Action 2)
        from uuid import UUID as _UUID

        target_id = _UUID(visible[2]["id"])
        result = await service.rollback_to_message(game_id, message_id=target_id)

        # Should delete Action 2 + Response 2, keep Action 1 + Response 1
        remaining = await service.load_chat_messages(game_id)
        assert len(remaining) == 2
        assert remaining[0]["content"] == "Action 1"
        assert remaining[1]["content"] == "Response 1"

    @pytest.mark.asyncio
    async def test_rollback_nonexistent_message_id(self, client, test_user, test_pool):
        """Rollback with unknown message ID returns deleted=0."""
        import uuid

        game_id, service, world_gen = await _setup_game_with_world(
            client, test_user, test_pool
        )

        result = await service.rollback_to_message(game_id, message_id=uuid.uuid4())
        assert result["deleted"] == 0

    @pytest.mark.asyncio
    async def test_load_chat_messages_includes_id(self, client, test_user, test_pool):
        """load_chat_messages includes message UUIDs."""
        from schema import NarrationOutput

        game_id, service, world_gen = await _setup_game_with_world(
            client, test_user, test_pool
        )
        arrival_loc = world_gen.arrival_event.arrival_location_ref

        narration = NarrationOutput.model_validate(_make_narration_output(arrival_loc))
        turn = await open_turn(test_pool, game_id)
        await apply_state(test_pool, game_id, narration, 1, turn_id=turn)
        await save_pair(
            test_pool,
            game_id,
            "Test",
            "Response",
            cycle=1,
            time="09h00",
            location_ref=arrival_loc,
            turn_id=turn,
        )

        messages = await service.load_chat_messages(game_id)
        assert len(messages) >= 2
        for msg in messages:
            assert "id" in msg
            assert isinstance(msg["id"], str)
            assert len(msg["id"]) == 36  # UUID format


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

        resp = await client.post("/api/games", headers=auth_headers(test_user["token"]))
        game_id = UUID(resp.json()["gameId"])
        service = GameService(test_pool)

        # Before world creation, world_created should be false
        # but game should still load (no protagonist means default stats)
        state = await service.load_game_state(game_id)
        assert state["world_created"] is False

    @pytest.mark.asyncio
    async def test_load_world_info_after_population(self, client, test_user, test_pool):
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

        resp = await client.post("/api/games", headers=auth_headers(test_user["token"]))
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

        resp = await client.post("/api/games", headers=auth_headers(test_user["token"]))
        game_id = UUID(resp.json()["gameId"])
        service = GameService(test_pool)

        # Should not raise — test_user["id"] is already a UUID from asyncpg
        user_id = test_user["id"]
        await service.verify_ownership(game_id, user_id)

    @pytest.mark.asyncio
    async def test_unauthorized_access(self, client, test_user, second_user, test_pool):
        """verify_ownership raises GameAccessDenied (403) for a different user."""
        from domain.errors import GameAccessDenied
        from services.game_service import GameService

        resp = await client.post("/api/games", headers=auth_headers(test_user["token"]))
        game_id = UUID(resp.json()["gameId"])
        service = GameService(test_pool)

        other_id = second_user["id"]
        with pytest.raises(GameAccessDenied):
            await service.verify_ownership(game_id, other_id)

    @pytest.mark.asyncio
    async def test_nonexistent_game(self, client, test_user, test_pool):
        """verify_ownership raises GameNotFound (404) for a non-existent game."""
        from uuid import uuid4

        from domain.errors import GameNotFound
        from services.game_service import GameService

        service = GameService(test_pool)

        user_id = test_user["id"]
        with pytest.raises(GameNotFound):
            await service.verify_ownership(uuid4(), user_id)


# =============================================================================
# GAME SERVICE - build_llm_messages
# =============================================================================


class TestBuildLLMMessages:
    """Tests for GameService.build_llm_messages()"""

    @pytest.mark.asyncio
    async def test_build_llm_messages_with_history(self, client, test_user, test_pool):
        """build_llm_messages builds correct message array with history."""
        game_id, service, world_gen = await _setup_game_with_world(
            client, test_user, test_pool
        )
        arrival_loc = world_gen.arrival_event.arrival_location_ref

        # Save two rounds of messages
        times = ["09h15", "09h45"]
        for i in range(2):
            await save_pair(
                test_pool,
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
    async def test_build_llm_messages_empty_history(self, client, test_user, test_pool):
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
# EXTRACTOR WRITES (the extractors' write path, by entity id)
# =============================================================================


async def _extract(test_pool, game_id, extractor_cls, raw_result, cycle=2) -> dict:
    """Run one extractor's real write path with a canned LLM result; its stats."""
    from llm.session import LLMSession
    from tests.test_llm_session import FakeProvider

    extractor = extractor_cls(test_pool, game_id, LLMSession.from_provider(FakeProvider()))

    async def fake_call(*_args, **_kwargs):
        return raw_result, {"cost_usd": 0.0}

    extractor._call_llm = fake_call
    return (await extractor.run("texte", {}, cycle))["stats"]


def _characters():
    from services.extraction.characters import CharactersExtractor

    return CharactersExtractor


def _arcs():
    from services.extraction.narrative_arcs import NarrativeArcsExtractor

    return NarrativeArcsExtractor


def _inventory():
    from services.extraction.inventory import InventoryExtractor

    return InventoryExtractor


class TestExtractorWrites:
    """Extracted items written through IdentityService and by id."""

    @pytest.mark.asyncio
    async def test_facts_are_created(self, client, test_user, test_pool):
        game_id, _, _ = await _setup_game_with_world(client, test_user, test_pool)
        stats = await _extract(test_pool, game_id, _characters(), {"facts": [{
            "fact_type": "revelation",
            "description": "Ossek révèle qu'iel est seul de son espèce sur la station",
            "semantic_key": "ossek:revele:seul_espece",
            "importance": 4,
            "location_ref": "Le Quart de Cycle",
            "participants": [{"entity_ref": "Ossek", "role": "actor"},
                             {"entity_ref": "Valentin", "role": "witness"}],
        }]})

        assert stats["facts_created"] == 1
        assert stats["errors"] == []
        async with test_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT location_id, (SELECT count(*) FROM fact_participants"
                " WHERE fact_id = f.id) AS participants FROM facts f"
                " WHERE game_id = $1 AND semantic_key = 'ossek:revele:seul_espece'",
                game_id,
            )
        assert row["location_id"] is not None
        assert row["participants"] == 2

    @pytest.mark.asyncio
    async def test_character_is_created(self, client, test_user, test_pool):
        game_id, _, _ = await _setup_game_with_world(client, test_user, test_pool)
        stats = await _extract(test_pool, game_id, _characters(), {"entities_created": [{
            "name": "Elena Vasquez",
            "known_by_protagonist": True,
            "data": {"description": "Grande, cheveux courts noirs", "species": "human",
                     "gender": "femme", "occupation": "ingénieure réseau",
                     "mood": "anxieuse"},
        }]})

        assert stats["entities_created"] == 1
        async with test_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT name, occupation, known_by_protagonist, created_cycle"
                " FROM characters WHERE game_id = $1 AND name = 'Elena Vasquez'",
                game_id,
            )
        assert row is not None
        assert row["occupation"] == "ingénieure réseau"
        assert row["known_by_protagonist"] is True
        assert row["created_cycle"] == 2

    @pytest.mark.asyncio
    async def test_location_is_created(self, client, test_user, test_pool):
        from services.extraction.locations import LocationsExtractor

        game_id, _, _ = await _setup_game_with_world(client, test_user, test_pool)
        stats = await _extract(test_pool, game_id, LocationsExtractor, {"entities_created": [{
            "name": "Marché Noir Section 9",
            "data": {"location_type": "market", "sector": "Quartier Ouvrier",
                     "parent_location_ref": "Bloc Tournesol",
                     "description": "Un couloir sombre où des stands vendent de tout.",
                     "atmosphere": "tendue et animée"},
        }]})

        assert stats["entities_created"] == 1
        async with test_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT l.location_type, l.sector, p.name AS parent FROM locations l"
                " LEFT JOIN locations p ON p.id = l.parent_id"
                " WHERE l.game_id = $1 AND l.name = 'Marché Noir Section 9'",
                game_id,
            )
        assert tuple(row) == ("market", "Quartier Ouvrier", "Bloc Tournesol")

    @pytest.mark.asyncio
    async def test_organization_is_created(self, client, test_user, test_pool):
        from services.extraction.organizations import OrganizationsExtractor

        game_id, _, _ = await _setup_game_with_world(client, test_user, test_pool)
        stats = await _extract(test_pool, game_id, OrganizationsExtractor, {
            "entities_created": [{
                "name": "Syndicat des Dockers",
                "data": {"org_type": "union", "domain": "transport",
                         "description": "Syndicat influent qui contrôle le quai central."},
            }]})

        assert stats["entities_created"] == 1
        async with test_pool.acquire() as conn:
            org_type = await conn.fetchval(
                "SELECT org_type FROM organizations"
                " WHERE game_id = $1 AND name = 'Syndicat des Dockers'",
                game_id,
            )
        assert org_type == "union"

    @pytest.mark.asyncio
    async def test_acquired_object_is_created_in_the_inventory(
        self, client, test_user, test_pool
    ):
        game_id, _, _ = await _setup_game_with_world(client, test_user, test_pool)
        stats = await _extract(test_pool, game_id, _inventory(), {"objects_created": [{
            "name": "Carte d'accès niveau 2",
            "category": "tech",
            "description": "Carte magnétique bleue avec puce intégrée",
            "transportable": True,
            "stackable": False,
            "base_value": 50,
            "quantity": 1,
            "from_hint": "Carte d'accès temporaire",
        }]})

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
        assert obj["base_value"] == 50
        assert inv_qty == 1

    @pytest.mark.asyncio
    async def test_entity_is_updated(self, client, test_user, test_pool):
        game_id, _, _ = await _setup_game_with_world(client, test_user, test_pool)
        stats = await _extract(test_pool, game_id, _characters(), {"entities_updated": [{
            "entity_ref": "Ossek", "changes": {"mood": "plus détendu, presque souriant"},
        }]})

        assert stats["entities_updated"] == 1
        async with test_pool.acquire() as conn:
            mood = await conn.fetchval(
                "SELECT mood FROM characters WHERE game_id = $1 AND name = 'Ossek'",
                game_id,
            )
        assert mood == "plus détendu, presque souriant"

    @pytest.mark.asyncio
    async def test_update_without_type_finds_the_entity_type(
        self, client, test_user, test_pool
    ):
        """An update whose type is null resolves its reference among every type."""
        game_id, _, _ = await _setup_game_with_world(client, test_user, test_pool)
        stats = await _extract(test_pool, game_id, _characters(), {"entities_updated": [{
            "entity_ref": "Ossek", "entity_type": None,
            "changes": {"mood": "curieux et attentif"},
        }]})

        assert (stats["entities_updated"], stats["errors"]) == (1, [])
        async with test_pool.acquire() as conn:
            mood = await conn.fetchval(
                "SELECT mood FROM characters WHERE game_id = $1 AND name = 'Ossek'",
                game_id,
            )
        assert mood == "curieux et attentif"

    @pytest.mark.asyncio
    async def test_relation_is_created(self, client, test_user, test_pool):
        game_id, _, _ = await _setup_game_with_world(client, test_user, test_pool)
        stats = await _extract(test_pool, game_id, _arcs(), {"relations_created": [{
            "cycle": 2,
            "relation": {"source_ref": "Valentin", "target_ref": "Ossek",
                         "relation_type": "knows", "known_by_protagonist": True,
                         "level": 2, "context": "Rencontre au Quart de Cycle"},
        }]})

        assert stats["relations_created"] == 1
        async with test_pool.acquire() as conn:
            rel = await conn.fetchrow(
                """SELECT r.level FROM relations r
                   JOIN entity_registry src ON r.source_id = src.id
                   JOIN entity_registry tgt ON r.target_id = tgt.id
                   WHERE r.game_id = $1 AND src.entity_type = 'protagonist'
                     AND tgt.name = 'Ossek' AND r.type = 'knows'
                     AND r.end_cycle IS NULL""",
                game_id,
            )
        assert rel["level"] == 2

    @pytest.mark.asyncio
    async def test_owns_relations_are_skipped(self, client, test_user, test_pool):
        """OWNS is the inventory's."""
        game_id, _, _ = await _setup_game_with_world(client, test_user, test_pool)
        stats = await _extract(test_pool, game_id, _arcs(), {"relations_created": [{
            "cycle": 2,
            "relation": {"source_ref": "Valentin", "target_ref": "Terminal personnel",
                         "relation_type": "owns", "known_by_protagonist": True},
        }]})
        assert stats["relations_created"] == 0

    @pytest.mark.asyncio
    async def test_event_is_scheduled(self, client, test_user, test_pool):
        game_id, _, _ = await _setup_game_with_world(client, test_user, test_pool)
        stats = await _extract(test_pool, game_id, _arcs(), {"events_scheduled": [{
            "event_type": "appointment",
            "title": "Déjeuner avec Ossek",
            "description": "RDV informel au Quart de Cycle",
            "planned_cycle": 5,
            "time": "12h30",
            "location_ref": "Le Quart de Cycle",
            "participants": ["Ossek"],
        }]})

        assert (stats["events_scheduled"], stats["errors"]) == (1, [])
        async with test_pool.acquire() as conn:
            event = await conn.fetchrow(
                "SELECT planned_cycle, time, location_id,"
                " (SELECT count(*) FROM event_participants WHERE event_id = e.id)"
                " AS participants FROM events e"
                " WHERE game_id = $1 AND title = 'Déjeuner avec Ossek'",
                game_id,
            )
        assert (event["planned_cycle"], event["time"]) == (5, "12h30")
        assert event["location_id"] is not None
        assert event["participants"] == 1

    @pytest.mark.asyncio
    async def test_event_keeps_going_without_an_unresolved_place(
        self, client, test_user, test_pool
    ):
        """C12: an event whose place does not resolve is written without it, counted."""
        game_id, _, _ = await _setup_game_with_world(client, test_user, test_pool)
        stats = await _extract(test_pool, game_id, _arcs(), {"events_scheduled": [{
            "event_type": "appointment", "title": "Rendez-vous flou", "planned_cycle": 4,
            "location_ref": "Nulle Part",
        }]})

        assert stats["events_scheduled"] == 1
        assert stats["errors"] == [{"code": "ref_dropped", "item": "event location"}]
        async with test_pool.acquire() as conn:
            location_id = await conn.fetchval(
                "SELECT location_id FROM events WHERE game_id = $1"
                " AND title = 'Rendez-vous flou'",
                game_id,
            )
        assert location_id is None

    @pytest.mark.asyncio
    async def test_chronology_is_saved(self, client, test_user, test_pool):
        game_id, _, _ = await _setup_game_with_world(client, test_user, test_pool)
        await _extract(test_pool, game_id, _arcs(), {
            "segment_summary": "Valentin commande un café au Quart de Cycle."})

        async with test_pool.acquire() as conn:
            chrono = await conn.fetchrow(
                "SELECT summary FROM chronology WHERE game_id = $1 AND cycle = 2",
                game_id,
            )
        assert "café" in chrono["summary"].lower()

    @pytest.mark.asyncio
    async def test_inventory_lose(self, client, test_user, test_pool):
        game_id, _, _ = await _setup_game_with_world(client, test_user, test_pool)
        quantity = """SELECT i.quantity FROM inventory i
                      JOIN objects o ON i.object_id = o.id
                      WHERE i.game_id = $1 AND o.name = 'Terminal personnel'"""
        async with test_pool.acquire() as conn:
            inv_before = await conn.fetchval(quantity, game_id)
        assert inv_before is not None

        await _extract(test_pool, game_id, _inventory(), {"inventory_changes": [{
            "action": "lose", "object_ref": "Terminal personnel", "quantity_delta": 1,
            "reason": "Volé dans le terminal",
        }]})

        async with test_pool.acquire() as conn:
            inv_after = await conn.fetchval(quantity, game_id)
        assert inv_after is None or inv_after < inv_before

    @pytest.mark.asyncio
    async def test_inventory_use_creates_a_fact(self, client, test_user, test_pool):
        game_id, _, _ = await _setup_game_with_world(client, test_user, test_pool)
        await _extract(test_pool, game_id, _inventory(), {"inventory_changes": [{
            "action": "use", "object_ref": "Terminal personnel", "quantity_delta": 1,
            "reason": "Consulter les messages",
        }]})

        async with test_pool.acquire() as conn:
            fact = await conn.fetchrow(
                "SELECT description FROM facts"
                " WHERE game_id = $1 AND semantic_key LIKE 'protagonist:use:%'",
                game_id,
            )
        assert "Terminal personnel" in fact["description"]

    @pytest.mark.asyncio
    async def test_ambient_update(self, client, test_user, test_pool):
        from services.extraction.locations import LocationsExtractor

        game_id, _, _ = await _setup_game_with_world(client, test_user, test_pool)
        stats = await _extract(test_pool, game_id, LocationsExtractor, {"ambient_updates": [{
            "entity_ref": "Le Quart de Cycle",
            "ambient": "L'endroit semble plus animé ce soir.",
        }]})

        assert stats["ambients_updated"] == 1
        async with test_pool.acquire() as conn:
            ambient = await conn.fetchval(
                "SELECT ambient FROM locations"
                " WHERE game_id = $1 AND name = 'Le Quart de Cycle'",
                game_id,
            )
        assert "animé" in ambient

    @pytest.mark.asyncio
    async def test_entity_reveal_via_update(self, client, test_user, test_pool):
        """An update with now_known=True is a reveal (IdentityService.reveal)."""
        game_id, _, _ = await _setup_game_with_world(client, test_user, test_pool)
        known = """SELECT known_by_protagonist, mood FROM characters
                   WHERE game_id = $1 AND name = 'Justine Lépicier'"""
        async with test_pool.acquire() as conn:
            assert (await conn.fetchrow(known, game_id))["known_by_protagonist"] is False

        await _extract(test_pool, game_id, _characters(), {"entities_updated": [{
            "entity_ref": "Justine Lépicier", "now_known": True,
            "changes": {"mood": "souriante et détendue"},
        }]})

        async with test_pool.acquire() as conn:
            row = await conn.fetchrow(known, game_id)
        assert row["known_by_protagonist"] is True
        assert row["mood"] == "souriante et détendue"

    @pytest.mark.asyncio
    async def test_reveal_by_descriptor_with_article_marks_the_character_known(
        self, client, test_user, test_pool
    ):
        """The Kethari case (#152): an NPC extracted under a description is stored with it as
        descriptor; a reveal naming it with an article finds it (find_entity), sets its true
        name and marks it known, registry included."""
        game_id, _, _ = await _setup_game_with_world(client, test_user, test_pool)
        await _extract(test_pool, game_id, _characters(), {"entities_created": [{
            "name": "Kethari âgée", "known_by_protagonist": False}]})

        async with test_pool.acquire() as conn:
            created = await conn.fetchrow(
                "SELECT id, true_name, descriptor FROM characters"
                " WHERE game_id = $1 AND name = 'Kethari âgée'",
                game_id,
            )
            identity = await IdentityService.for_game(conn, game_id)
            revealed = await identity.reveal(
                conn,
                EntityRef("La Kethari âgée", "character"),
                "Nahle Irun-Sa",
                turn_id=None,
                source="reveal",
            )
            row = await conn.fetchrow(
                "SELECT c.known_by_protagonist, c.true_name, c.descriptor, er.name AS label,"
                " display_for_player(c.id) AS shown"
                " FROM characters c JOIN entity_registry er ON er.id = c.id"
                " WHERE c.id = $1",
                created["id"],
            )
        assert (created["true_name"], created["descriptor"]) == (None, "Kethari âgée")
        assert revealed.kind == "applied"
        assert dict(row) == {
            "known_by_protagonist": True,
            "true_name": "Nahle Irun-Sa",
            "descriptor": "Kethari âgée",
            "label": "Nahle Irun-Sa",
            "shown": "Nahle Irun-Sa",
        }


# =============================================================================
# GAME SERVICE — load_npcs / load_locations / load_organizations / load_quests
# =============================================================================


class TestGameServiceLoadSidebar:
    """Tests for sidebar data loading (load_npcs, load_locations, etc.)."""

    @pytest.mark.asyncio
    async def test_load_npcs_returns_list_of_dicts(self, client, test_user, test_pool):
        """load_npcs returns properly typed list after making a character known."""

        game_id, service, world_gen = await _setup_game_with_world(
            client, test_user, test_pool
        )

        # World gen characters start as unknown — mark one known
        first_char = world_gen.characters[0].name
        async with test_pool.acquire() as conn:
            identity = await IdentityService.for_game(conn, game_id)
            await identity.reveal(
                conn,
                EntityRef(first_char, "character"),
                None,
                turn_id=None,
                source="reveal",
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
                "Inconnu",
                "Hostile",
                "Neutre",
                "Connaissance",
                "Ami",
                "Ami proche",
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
                "personal",
                "professional",
                "social",
                "mystery",
                "health",
                "family",
                "financial",
                "community",
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
    async def test_build_events_returns_typed_list(self, client, test_user, test_pool):
        """_build_events returns list of EventSummary from DB."""
        from services.context_builder import ContextBuilder
        from kg.populator import KnowledgeGraphPopulator

        game_id, service, world_gen = await _setup_game_with_world(
            client, test_user, test_pool
        )

        # Create an event in the DB
        async with test_pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO events (game_id, title, type, planned_cycle)
                   VALUES ($1, 'Réunion urgente', 'appointment', 2)""",
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
    async def test_build_facts_returns_typed_list(self, client, test_user, test_pool):
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
        await store_requests(test_pool, game_id, [npc_name])

        builder = ContextBuilder(test_pool, game_id)
        async with test_pool.acquire() as conn:
            details = await builder._build_requested_details(conn)

        assert isinstance(details, dict)
        assert npc_name in details
        assert isinstance(details[npc_name], dict)

    @pytest.mark.asyncio
    async def test_active_arcs_from_context_builder(self, client, test_user, test_pool):
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
            "display_name": "Elena",
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
            "display_name": "Raj",
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
            "display_name": "Zed",
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
            "display_name": "Silhouette",
            "known_by_protagonist": False,
            "descriptor": "Silhouette",
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
            session=MagicMock(),
        )

        assert isinstance(result, dict)
        assert "extractors" in result
        assert len(result["extractors"]) == 0


# =============================================================================
# FIRST-TURN RESOLVER REFERENCE
# =============================================================================


class TestFirstTurnResolver:
    """Test that the resolver can build a reference for the first message."""

    @pytest.mark.asyncio
    async def test_first_turn_reference_built(self, client, test_user, test_pool):
        """_build_first_turn_reference returns entity names from DB."""
        from services.extraction.orchestrator import _build_first_turn_reference

        game_id, service, world_gen = await _setup_game_with_world(
            client, test_user, test_pool
        )

        text, annotations = await _build_first_turn_reference(test_pool, game_id)

        assert len(text) > 0
        assert annotations is not None
        assert len(annotations) > 0

        # Should contain world gen entity names
        entity_names = [a[2] for a in annotations]
        assert len(entity_names) > 0

        # Each annotation should have [start, end, name, type]
        for ann in annotations:
            assert len(ann) == 4
            assert isinstance(ann[0], int)
            assert isinstance(ann[1], int)
            assert isinstance(ann[2], str)
            assert ann[3] in ("character", "location", "organization")
