"""commit_turn: one transaction for every write of the turn, dice effects included (#16, #20)."""

import json
from types import SimpleNamespace
from uuid import UUID

import pytest
import pytest_asyncio

from pipeline.context import TurnContext, TurnRequest
from pipeline.steps.arbitrate import Arbitration
from pipeline.steps.commit import commit_turn
from pipeline.steps.load import Prepared
from pipeline.steps.narrate import Narrated
from repos import turns
from repos.games import get_snapshot
from schema import NarrationOutput
from schema.engine import MechanicalDecision, MechanicalResult, RollResult
from services.engine import fate_core, get_engine
from services.game_service import GameService
from tests.characterization import payloads
from tests.characterization.conftest import harness, llm_mode, scripted_llm  # noqa: F401

STRESS = {"stress_type": "physical", "stress_amount": 1}


@pytest_asyncio.fixture
async def fate_game(harness):  # noqa: F811
    """Fate game with world generated and arrival played; LLM call log reset."""
    game_id = await harness.create_game("fate_core")
    await harness.init_world(game_id, engine="fate_core",
                             character_data=payloads.CHARACTER_DATA["fate_core"])
    await harness.chat(game_id, "__ARRIVEE__")
    await harness.drain()
    harness.llm.calls.clear()
    return game_id


async def _engine_state(pool, game_id) -> dict:
    async with pool.acquire() as conn:
        game = await conn.fetchrow(
            "SELECT current_cycle, engine_locked FROM games WHERE id = $1", game_id)
        return {
            "stress": list(await conn.fetchval(
                "SELECT stress_physical FROM character_fate WHERE game_id = $1", game_id)),
            "cycle": game["current_cycle"],
            "engine_locked": game["engine_locked"],
            "messages": await conn.fetchval(
                "SELECT count(*) FROM messages WHERE game_id = $1", game_id),
            "rolls": await conn.fetchval(
                "SELECT count(*) FROM mechanic_rolls WHERE game_id = $1", game_id),
        }


class _NullSink:
    def __getattr__(self, name):
        async def ignore(*args, **kwargs):
            return None
        return ignore


async def test_failure_mid_commit_rolls_back_everything(harness, fate_game, monkeypatch):  # noqa: F811
    game_id = UUID(fate_game)
    pool = harness.pool
    async with pool.acquire() as conn:
        # First narration turn of the game: the commit would lock the engine.
        await conn.execute("UPDATE games SET engine_locked = FALSE WHERE id = $1", game_id)
        snapshot = await get_snapshot(conn, game_id)
    before = await _engine_state(pool, game_id)

    roll = RollResult(dice=[1, 1, 1, 1], total=4, skill_total=6, outcome="success",
                      shifts=4, details={"skill_name": "Athlétisme", **STRESS})
    arbitration = Arbitration(
        mechanical=MechanicalResult(decision=MechanicalDecision(requires_test=True), roll=roll),
        resumed_roll_id=None,
    )
    narration = NarrationOutput.model_validate({
        **json.loads(payloads.NARRATION),
        "day_transition": {"new_cycle": 2, "new_date": "Mardi 19 Juillet 2847"},
    })
    narrated = Narrated(narration=narration, display_text=narration.narrative_text, cost=None)
    ctx = TurnContext(
        request=TurnRequest(game_id=game_id, user_id=None, message="Je saute."),
        snapshot=snapshot, session=None, sink=_NullSink(), pool=pool,
        engine=get_engine("fate_core"), ref="test",
    )

    async def boom(*args, **kwargs):
        raise RuntimeError("disk full")

    # Last write of the transaction: roll effects, state, deltas, messages and roll log
    # have all been written when it fails, so every assertion below can catch a leak.
    monkeypatch.setattr(turns, "lock_engine", boom)
    with pytest.raises(RuntimeError):
        await commit_turn(ctx, Prepared(player_input="Je saute.", is_arrival=False,
                                        context=None), arbitration, narrated)

    assert await _engine_state(pool, game_id) == before


def _stress_on_every_roll(monkeypatch):
    """Successful Fate rolls (all +1) whose details also check a physical stress box."""
    monkeypatch.setattr(fate_core, "random", SimpleNamespace(choice=lambda seq: 1))
    original = fate_core.FateCoreEngine.roll_dice

    def roll_with_stress(self, decision):
        roll = original(self, decision)
        roll.details.update(STRESS)
        return roll

    monkeypatch.setattr(fate_core.FateCoreEngine, "roll_dice", roll_with_stress)


async def test_failed_narration_leaves_engine_state_untouched(harness, fate_game,  # noqa: F811
                                                              monkeypatch):
    """#16: a roll whose narration fails must not tick stress."""
    game_id = fate_game
    harness.llm._responses["mechanical"] = payloads.mechanical(
        requires_test=True, skill="Athlétisme", skill_value=2, difficulty=1)
    harness.llm._responses["narration"] = json.dumps(
        {**json.loads(payloads.NARRATION), "narrative_text": ""})
    _stress_on_every_roll(monkeypatch)
    before = await _engine_state(harness.pool, UUID(game_id))

    events = await harness.chat(game_id, "Je saute par-dessus la barrière.")
    await harness.drain()

    types = [e["type"] for e in events]
    assert "roll_result" in types
    assert types.count("error") == 1
    assert "done" not in types
    assert await _engine_state(harness.pool, UUID(game_id)) == before


async def test_commit_failure_sends_one_error_and_no_done(harness, fate_game,  # noqa: F811
                                                          monkeypatch):
    game_id = fate_game
    harness.llm._responses["mechanical"] = payloads.mechanical(
        requires_test=True, skill="Athlétisme", skill_value=2, difficulty=1)
    _stress_on_every_roll(monkeypatch)
    before = await _engine_state(harness.pool, UUID(game_id))

    async def boom(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(turns, "save_turn_messages", boom)
    events = await harness.chat(game_id, "Je saute par-dessus la barrière.")
    await harness.drain()

    types = [e["type"] for e in events]
    assert types.count("error") == 1
    assert "done" not in types
    assert await _engine_state(harness.pool, UUID(game_id)) == before


async def test_commit_failure_on_resumed_roll_keeps_it_pending(harness, fate_game,  # noqa: F811
                                                               monkeypatch):
    """A resumed roll whose commit fails stays pending, fate points untouched (#16, #32)."""
    game_id = fate_game
    harness.llm._responses["mechanical"] = payloads.mechanical(
        requires_test=True, skill="Athlétisme", skill_value=0, difficulty=4)
    monkeypatch.setattr(fate_core, "random", SimpleNamespace(choice=lambda seq: -1))
    events = await harness.chat(game_id, "Je tente un saut impossible.")
    roll_id = next(e["roll_id"] for e in events if e["type"] == "roll_pending")
    async with harness.pool.acquire() as conn:
        fp_before = await conn.fetchval(
            "SELECT fate_points FROM character_fate WHERE game_id = $1", UUID(game_id))

    async def boom(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(turns, "save_turn_messages", boom)
    resumed = await harness.chat(game_id, "Je tente un saut impossible.", roll_id=roll_id,
                                 invoked_aspects=["Pilote déchu en quête de rédemption"])
    await harness.drain()

    types = [e["type"] for e in resumed]
    assert types.count("error") == 1
    assert "done" not in types
    async with harness.pool.acquire() as conn:
        stored = await turns.get_pending_roll(conn, UUID(game_id))
        fp_after = await conn.fetchval(
            "SELECT fate_points FROM character_fate WHERE game_id = $1", UUID(game_id))
    assert stored is not None and str(stored["id"]) == roll_id
    assert fp_after == fp_before


SAVED_DISPLAY_FAILED = "Ton action est enregistrée, mais l'affichage a échoué. Recharge la partie."


async def test_failure_after_commit_is_not_retryable(harness, fate_game, monkeypatch):  # noqa: F811
    """A saved turn whose display fails must not invite a resend (it would play twice)."""
    game_id = fate_game
    before = await _engine_state(harness.pool, UUID(game_id))

    async def boom(self, gid):
        raise RuntimeError("connection reset")

    monkeypatch.setattr(GameService, "load_game_state", boom)
    events = await harness.chat(game_id, "Je regarde autour.")
    await harness.drain()

    errors = [e for e in events if e["type"] == "error"]
    assert len(errors) == 1
    assert errors[0]["code"] == "saved_display_failed"
    assert errors[0]["error"] == SAVED_DISPLAY_FAILED
    assert errors[0]["recoverable"] is False
    assert "Réessaie" not in errors[0]["error"]
    after = await _engine_state(harness.pool, UUID(game_id))
    assert after["messages"] == before["messages"] + 2


async def test_failure_after_world_saved_is_not_retryable(harness, monkeypatch):  # noqa: F811
    """Same for world generation: once process_init saved the world, no resend."""
    game_id = await harness.create_game("none")

    async def boom(self, gid):
        raise RuntimeError("connection reset")

    monkeypatch.setattr(GameService, "load_game_state", boom)
    events = await harness.init_world(game_id)

    errors = [e for e in events if e["type"] == "error"]
    assert [(e["code"], e["error"], e["recoverable"]) for e in errors] == [
        ("saved_display_failed", SAVED_DISPLAY_FAILED, False)]
    async with harness.pool.acquire() as conn:
        assert (await get_snapshot(conn, UUID(game_id))).world_created is True
