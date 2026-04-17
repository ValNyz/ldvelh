"""Tests for Director service and schema."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from services.director_service import should_run_director, _parse_ig_hours
from schema.director import DirectorOutput, PlannedEvent


# =============================================================================
# UNIT TESTS — should_run_director
# =============================================================================


class TestParseIGHours:
    def test_normal(self):
        assert _parse_ig_hours("14h30") == 14.5

    def test_midnight(self):
        assert _parse_ig_hours("00h00") == 0.0

    def test_no_minutes(self):
        assert _parse_ig_hours("08h00") == 8.0

    def test_invalid(self):
        assert _parse_ig_hours("invalid") == 0.0

    def test_empty(self):
        assert _parse_ig_hours("") == 0.0

    def test_none(self):
        assert _parse_ig_hours(None) == 0.0


class TestShouldRunDirector:

    def test_first_run_always_triggers(self):
        assert should_run_director("10h00", None, "medium") is True

    def test_within_interval_no_trigger(self):
        assert should_run_director("10h00", "08h00", "medium") is False

    def test_at_interval_triggers(self):
        assert should_run_director("14h00", "08h00", "medium") is True

    def test_past_interval_triggers(self):
        assert should_run_director("16h00", "08h00", "medium") is True

    def test_short_game_shorter_interval(self):
        assert should_run_director("12h00", "08h00", "short") is True
        assert should_run_director("11h00", "08h00", "short") is False

    def test_long_game_longer_interval(self):
        assert should_run_director("15h00", "08h00", "long") is False
        assert should_run_director("16h00", "08h00", "long") is True

    def test_day_wrap(self):
        # last=22h, current=03h → 5h elapsed. Medium needs 6h → no trigger
        assert should_run_director("03h00", "22h00", "medium") is False
        # last=22h, current=05h → 7h elapsed → trigger
        assert should_run_director("05h00", "22h00", "medium") is True

    def test_unknown_duration_uses_medium(self):
        # Unknown duration → 6h interval. 6h elapsed → trigger
        assert should_run_director("14h00", "08h00", "unknown") is True


# =============================================================================
# UNIT TESTS — DirectorOutput schema
# =============================================================================


class TestDirectorSchema:

    def test_minimal_output(self):
        out = DirectorOutput(tension_level=3, narrator_guidance="Test guidance")
        assert out.tension_level == 3
        assert out.planned_events == []
        assert out.long_term_vision == ""

    def test_full_output(self):
        out = DirectorOutput(
            tension_level=4,
            narrator_guidance="Elena prépare sa confrontation. Raj est nerveux.",
            planned_events=[
                PlannedEvent(cycle=5, event="Panne dans la raffinerie", location="Raffinerie"),
                PlannedEvent(cycle=7, event="Livraison annulée"),
            ],
            long_term_vision="Le saboteur sera révélé au cycle 15.",
        )
        assert len(out.planned_events) == 2
        assert out.planned_events[0].location == "Raffinerie"
        assert out.planned_events[1].location is None

    def test_tension_too_low(self):
        with pytest.raises(Exception):
            DirectorOutput(tension_level=0, narrator_guidance="test")

    def test_tension_too_high(self):
        with pytest.raises(Exception):
            DirectorOutput(tension_level=6, narrator_guidance="test")

    def test_default_values(self):
        out = DirectorOutput()
        assert out.tension_level == 3
        assert out.narrator_guidance == ""

    def test_planned_event_minimal(self):
        event = PlannedEvent(cycle=3, event="Something happens")
        assert event.location is None
        assert event.npcs_involved == []


# =============================================================================
# INTEGRATION TEST — Director pipeline (mocked LLM)
# =============================================================================


@pytest.mark.asyncio
@pytest.mark.integration
async def test_director_stores_plan(test_pool, test_user):
    """Director stores a plan in DB after world gen."""
    from services.game_service import GameService
    from schema import WorldGeneration
    from prompts.examples import WORLD_GENERATION_EXAMPLE

    service = GameService(test_pool)
    game_id = await service.create_game(test_user["id"])

    # Set game_duration
    async with test_pool.acquire() as conn:
        await conn.execute(
            "UPDATE games SET game_duration = 'medium' WHERE id = $1", game_id
        )

    world_gen_data = json.loads(WORLD_GENERATION_EXAMPLE)
    world_gen = WorldGeneration.model_validate(world_gen_data)
    await service.process_init(game_id, world_gen)

    # Mock the LLM call
    mock_result = {
        "tension_level": 3,
        "narrator_guidance": "Elena is stressed. Plant clues about sabotage.",
        "planned_events": [
            {"cycle": 2, "event": "Power outage in sector B"}
        ],
        "long_term_vision": "Saboteur reveal at cycle 10.",
    }

    mock_content = json.dumps(mock_result)
    mock_completion = AsyncMock()
    mock_completion.content = mock_content
    mock_provider = AsyncMock()
    mock_provider.complete = AsyncMock(return_value=mock_completion)

    with patch("services.director_service.get_provider", return_value=mock_provider):
        from services.director_service import run_director
        result = await run_director(
            pool=test_pool,
            game_id=game_id,
            current_cycle=1,
            current_time="08h00",
        )

    assert result is not None
    assert result["tension_level"] == 3

    # Verify stored in DB
    async with test_pool.acquire() as conn:
        plan = await conn.fetchrow(
            "SELECT * FROM director_plans WHERE game_id = $1", game_id
        )
    assert plan is not None
    assert plan["tension_level"] == 3
    assert plan["ig_time"] == "08h00"
    assert "Elena" in plan["narrator_guidance"]

    # Verify last_director_time updated
    async with test_pool.acquire() as conn:
        game = await conn.fetchrow(
            "SELECT last_director_time FROM games WHERE id = $1", game_id
        )
    assert game["last_director_time"] == "08h00"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_director_handles_empty_llm_result(test_pool, test_user):
    """Director handles empty LLM result gracefully."""
    from services.game_service import GameService
    from schema import WorldGeneration
    from prompts.examples import WORLD_GENERATION_EXAMPLE

    service = GameService(test_pool)
    game_id = await service.create_game(test_user["id"])

    world_gen_data = json.loads(WORLD_GENERATION_EXAMPLE)
    world_gen = WorldGeneration.model_validate(world_gen_data)
    await service.process_init(game_id, world_gen)

    mock_completion = AsyncMock()
    mock_completion.content = ""
    mock_provider = AsyncMock()
    mock_provider.complete = AsyncMock(return_value=mock_completion)

    with patch("services.director_service.get_provider", return_value=mock_provider):
        from services.director_service import run_director
        result = await run_director(
            pool=test_pool,
            game_id=game_id,
            current_cycle=1,
            current_time="08h00",
        )

    assert result is None

    # No plan stored
    async with test_pool.acquire() as conn:
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM director_plans WHERE game_id = $1", game_id
        )
    assert count == 0
