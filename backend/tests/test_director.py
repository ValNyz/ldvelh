"""Tests for Director service and schema."""

import json
from unittest.mock import patch

import pytest

from services.director_service import should_run_director, _parse_ig_hours
from schema.director import DirectorOutput, PlannedEvent
from llm.session import LLMSession


def _session(text):
    from tests.test_llm_session import FakeProvider
    return LLMSession.from_provider(FakeProvider(text=text))


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
    from tests.prompt_examples import WORLD_GENERATION_EXAMPLE

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

    session = _session(json.dumps(mock_result))
    from services.director_service import run_director
    result = await run_director(
        pool=test_pool,
        game_id=game_id,
        current_cycle=1,
        current_time="08h00",
        session=session,
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

    # Verify planned_events round-trips as a list, not a string
    assert isinstance(plan["planned_events"], list), (
        f"planned_events should be list, got {type(plan['planned_events'])}"
    )
    assert len(plan["planned_events"]) == 1
    assert plan["planned_events"][0]["event"] == "Power outage in sector B"

    # Verify last_director_time updated
    async with test_pool.acquire() as conn:
        game = await conn.fetchrow(
            "SELECT last_director_time FROM games WHERE id = $1", game_id
        )
    assert game["last_director_time"] == "08h00"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_director_plan_read_by_context_builder(test_pool, test_user):
    """Context builder reads director plan correctly (planned_events as list)."""
    from services.game_service import GameService
    from services.context_builder import ContextBuilder
    from schema import WorldGeneration
    from tests.prompt_examples import WORLD_GENERATION_EXAMPLE

    service = GameService(test_pool)
    game_id = await service.create_game(test_user["id"])

    async with test_pool.acquire() as conn:
        await conn.execute(
            "UPDATE games SET game_duration = 'medium' WHERE id = $1", game_id
        )

    world_gen_data = json.loads(WORLD_GENERATION_EXAMPLE)
    world_gen = WorldGeneration.model_validate(world_gen_data)
    await service.process_init(game_id, world_gen)

    # Mock the LLM call
    mock_result = {
        "tension_level": 4,
        "narrator_guidance": "Raise the stakes.",
        "planned_events": [
            {"cycle": 3, "event": "Explosion in lab", "location": "Labo"},
            {"cycle": 5, "event": "NPC betrayal", "npcs_involved": ["Raj"]},
        ],
        "long_term_vision": "Build toward confrontation.",
    }

    session = _session(json.dumps(mock_result))
    from services.director_service import run_director
    await run_director(
        pool=test_pool,
        game_id=game_id,
        current_cycle=1,
        current_time="08h00",
        session=session,
    )

    # Now read it back via context_builder's _load_director_plan
    builder = ContextBuilder(test_pool, game_id)
    async with test_pool.acquire() as conn:
        guidance, tension, events = await builder._load_director_plan(conn)

    assert tension == 4
    assert "stakes" in guidance
    assert isinstance(events, list)
    assert len(events) == 2
    assert events[0]["event"] == "Explosion in lab"
    assert events[1]["npcs_involved"] == ["Raj"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_director_plan_string_fallback(test_pool, test_user):
    """Context builder handles corrupted planned_events stored as JSON string."""
    from services.game_service import GameService
    from services.context_builder import ContextBuilder
    from schema import WorldGeneration
    from tests.prompt_examples import WORLD_GENERATION_EXAMPLE

    service = GameService(test_pool)
    game_id = await service.create_game(test_user["id"])

    world_gen_data = json.loads(WORLD_GENERATION_EXAMPLE)
    world_gen = WorldGeneration.model_validate(world_gen_data)
    await service.process_init(game_id, world_gen)

    # Simulate corrupted data: insert planned_events as a double-encoded JSON string
    # (this is what the old json.dumps() bug produced)
    corrupted_events = json.dumps([{"cycle": 2, "event": "Corrupted event"}])
    async with test_pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO director_plans
               (game_id, cycle, ig_time, tension_level, narrator_guidance, planned_events)
               VALUES ($1, 1, '08h00', 3, 'test', $2)""",
            game_id,
            corrupted_events,  # string, not list — simulates the bug
        )

    # Context builder should handle the string gracefully
    builder = ContextBuilder(test_pool, game_id)
    async with test_pool.acquire() as conn:
        guidance, tension, events = await builder._load_director_plan(conn)

    assert isinstance(events, list), (
        f"Expected list after string fallback, got {type(events)}"
    )
    assert len(events) == 1
    assert events[0]["event"] == "Corrupted event"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_director_handles_empty_llm_result(test_pool, test_user):
    """Director handles empty LLM result gracefully."""
    from services.game_service import GameService
    from schema import WorldGeneration
    from tests.prompt_examples import WORLD_GENERATION_EXAMPLE

    service = GameService(test_pool)
    game_id = await service.create_game(test_user["id"])

    world_gen_data = json.loads(WORLD_GENERATION_EXAMPLE)
    world_gen = WorldGeneration.model_validate(world_gen_data)
    await service.process_init(game_id, world_gen)

    session = _session("")
    from services.director_service import run_director
    result = await run_director(
        pool=test_pool,
        game_id=game_id,
        current_cycle=1,
        current_time="08h00",
        session=session,
    )

    assert result is None

    # No plan stored
    async with test_pool.acquire() as conn:
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM director_plans WHERE game_id = $1", game_id
        )
    assert count == 0


# =============================================================================
# #9 — cycle-aware trigger, per-game guard, arc dedup, schedule from DB
# =============================================================================


class TestShouldRunDirectorAcrossCycles:
    def test_same_cycle_within_interval(self):
        assert should_run_director("10h00", "08h00", "medium", current_cycle=1, last_cycle=1) is False

    def test_same_cycle_at_interval(self):
        assert should_run_director("14h00", "08h00", "medium", current_cycle=1, last_cycle=1) is True

    def test_elapsed_counts_whole_cycles(self):
        # Two in-game days later at a later hour: hour-of-day alone says 1h elapsed.
        assert should_run_director("11h00", "10h00", "medium", current_cycle=3, last_cycle=1) is True

    def test_next_cycle_short_night(self):
        # 22h00 cycle 1 -> 03h00 cycle 2 = 5h elapsed (< 6h medium interval).
        assert should_run_director("03h00", "22h00", "medium", current_cycle=2, last_cycle=1) is False


class TestApplyArcUpdateDedup:
    @pytest.mark.asyncio
    async def test_create_existing_unresolved_title_updates_instead(self, test_pool, test_user):
        from services.director_apply import _apply_arc_update
        from schema.director import ArcUpdate
        from services.game_service import GameService

        game_id = await GameService(test_pool).create_game(test_user["id"])
        update = ArcUpdate(action="create", title="La Dette", description="v1", domain="personal", intensity=2)
        again = ArcUpdate(action="create", title="la dette", description="v2", domain="personal", intensity=4)
        async with test_pool.acquire() as conn:
            await _apply_arc_update(conn, game_id, update, 1)
            await _apply_arc_update(conn, game_id, again, 2)
            rows = await conn.fetch(
                "SELECT title, description, intensity FROM narrative_arcs WHERE game_id = $1", game_id
            )
        assert len(rows) == 1
        assert rows[0]["description"] == "v2"
        assert rows[0]["intensity"] == 4


class TestDirectorGuards:
    @pytest.mark.asyncio
    async def test_concurrent_starts_for_same_game_call_llm_once(self, test_pool, test_user):
        """One Director per game at a time: the rule lives in pipeline/director_runs (#79)."""
        import asyncio
        from pipeline import director_runs
        from services.director_service import run_director
        from services.game_service import GameService
        from schema import WorldGeneration
        from tests.prompt_examples import WORLD_GENERATION_EXAMPLE

        service = GameService(test_pool)
        game_id = await service.create_game(test_user["id"])
        await service.process_init(game_id, WorldGeneration.model_validate(json.loads(WORLD_GENERATION_EXAMPLE)))

        from tests.test_llm_session import FakeProvider

        gate = asyncio.Event()

        class GatedProvider(FakeProvider):
            async def complete(self, *args, **kwargs):
                await gate.wait()
                return await FakeProvider.complete(self, *args, **kwargs)

        provider = GatedProvider(text=json.dumps({"tension_level": 3, "narrator_guidance": "g"}))
        session = LLMSession.from_provider(provider)
        first = director_runs.start(game_id, run_director(pool=test_pool, game_id=game_id, current_cycle=1, current_time="08h00", session=session))
        second = director_runs.start(game_id, run_director(pool=test_pool, game_id=game_id, current_cycle=1, current_time="08h00", session=session))
        gate.set()
        result = await first

        assert second is None
        assert provider.calls.count("complete") == 1
        assert result is not None

    @pytest.mark.asyncio
    async def test_reader_failure_returns_none_without_unbound_error(self, test_pool, test_user):
        from services.director_service import run_director
        from services.game_service import GameService

        game_id = await GameService(test_pool).create_game(test_user["id"])
        with patch("services.director_context.KnowledgeGraphReader.get_game", side_effect=RuntimeError("db down")):
            result = await run_director(pool=test_pool, game_id=game_id, current_cycle=1, current_time="08h00", session=_session("{}"))
        assert result is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_director_cost_is_recorded(test_pool, test_user):
    from llm.usage import UsageLedger
    from services.director_service import run_director
    from services.game_service import GameService
    from schema import WorldGeneration
    from tests.prompt_examples import WORLD_GENERATION_EXAMPLE
    from tests.test_llm_session import FakeProvider

    service = GameService(test_pool)
    game_id = await service.create_game(test_user["id"])
    await service.process_init(game_id, WorldGeneration.model_validate(json.loads(WORLD_GENERATION_EXAMPLE)))
    ledger = UsageLedger()
    session = LLMSession.from_provider(
        FakeProvider(text=json.dumps({"tension_level": 3, "narrator_guidance": "g"})), ledger)
    assert await run_director(pool=test_pool, game_id=game_id, current_cycle=1,
                              current_time="08h00", session=session) is not None
    assert ledger.get_summary()["purposes"]["director"]["calls"] == 1


STORY = "Le dragon de verre murmure"


class TestDirectorLogHygiene:
    """An invalid DirectorOutput carrying story text never leaks it at WARNING or above."""

    async def _run_invalid(self, test_pool, test_user, caplog):
        import logging

        from services.director_service import run_director
        from services.game_service import GameService

        game_id = await GameService(test_pool).create_game(test_user["id"])
        text = json.dumps({"tension_level": {"x": STORY}, "narrator_guidance": "g",
                           "planned_events": [], "long_term_vision": "v"})
        with caplog.at_level(logging.DEBUG):
            result = await run_director(test_pool, game_id, 1, "10h00", _session(text))
        assert result is None
        return caplog.records

    async def test_fragment_absent_from_warning_and_above(self, test_pool, test_user, caplog):
        import logging

        records = await self._run_invalid(test_pool, test_user, caplog)
        formatter = logging.Formatter()
        failed = [r for r in records if r.levelno >= logging.WARNING]
        assert any("[DIRECTOR] Failed" in r.getMessage() for r in failed)
        assert STORY not in "\n".join(formatter.format(r) for r in failed)

    async def test_fragment_at_debug_only_with_log_prompts(self, test_pool, test_user, caplog,
                                                          monkeypatch):
        import logging

        from config import get_settings

        monkeypatch.setenv("LOG_PROMPTS", "true")
        get_settings.cache_clear()
        try:
            records = await self._run_invalid(test_pool, test_user, caplog)
        finally:
            monkeypatch.delenv("LOG_PROMPTS")
            get_settings.cache_clear()
        formatter = logging.Formatter()
        debug = [r for r in records if r.levelno == logging.DEBUG]
        assert STORY in "\n".join(formatter.format(r) for r in debug)
