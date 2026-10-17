"""Pending Fate roll fixture: a game whose last turn paused on a failed roll (as in C-05)."""

from types import SimpleNamespace

import pytest_asyncio

from services.engine import fate_core
from tests.characterization import payloads

PENDING_ACTION = "Je tente un saut impossible."


@pytest_asyncio.fixture
async def pending(harness, monkeypatch):
    """(game_id, roll_pending event) of a Fate game waiting for an aspect invocation."""
    game_id = await harness.create_game("fate_core")
    await harness.init_world(game_id, engine="fate_core",
                             character_data=payloads.CHARACTER_DATA["fate_core"])
    await harness.chat(game_id, "__ARRIVEE__")
    await harness.drain()
    # One plain turn first, so the paused turn can be rolled back (the arrival cannot).
    await harness.chat(game_id, "Je regarde autour de moi.")
    await harness.drain()
    harness.llm._responses["mechanical"] = payloads.mechanical(
        requires_test=True, skill="Athlétisme", skill_value=0, difficulty=4)
    monkeypatch.setattr(fate_core, "random", SimpleNamespace(choice=lambda seq: -1))
    events = await harness.chat(game_id, PENDING_ACTION)
    rolls = [e for e in events if e["type"] == "roll_pending"]
    assert rolls, harness.summarize(events)
    harness.llm.calls.clear()
    return game_id, rolls[0]
