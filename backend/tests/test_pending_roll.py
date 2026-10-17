"""Pending Fate roll: resolved once, not dodgeable, restored on reload (#32)."""

from types import SimpleNamespace

import pytest_asyncio

from services.engine import fate_core
from tests.characterization import payloads
from tests.characterization.conftest import harness, llm_mode, scripted_llm  # noqa: F401
from tests.characterization.harness import spy_narration

HIGH_CONCEPT = "Pilote déchu en quête de rédemption"
TROUBLE = "Je dois de l'argent à tout le monde"
ACTION = "Je tente un saut impossible."


@pytest_asyncio.fixture
async def pending(harness, monkeypatch):  # noqa: F811
    """Fate game whose last turn paused on a failed roll (as in C-05): (game_id, roll_pending event)."""
    game_id = await harness.create_game("fate_core")
    await harness.init_world(game_id, engine="fate_core",
                             character_data=payloads.CHARACTER_DATA["fate_core"])
    await harness.chat(game_id, "__ARRIVEE__")
    await harness.drain()
    harness.llm._responses["mechanical"] = payloads.mechanical(
        requires_test=True, skill="Athlétisme", skill_value=0, difficulty=4)
    monkeypatch.setattr(fate_core, "random", SimpleNamespace(choice=lambda seq: -1))
    events = await harness.chat(game_id, ACTION)
    rolls = [e for e in events if e["type"] == "roll_pending"]
    assert rolls, harness.summarize(events)
    harness.llm.calls.clear()
    return game_id, rolls[0]


async def _fate_points(harness, game_id):  # noqa: F811
    async with harness.pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT fate_points FROM character_fate WHERE game_id = $1", game_id)


async def _messages(harness, game_id):  # noqa: F811
    async with harness.pool.acquire() as conn:
        return await conn.fetch(
            "SELECT role, content FROM messages WHERE game_id = $1 ORDER BY created_at, sequence",
            game_id)


def _errors(events):
    return [e for e in events if e["type"] == "error"]


async def test_resume_twice_applies_once(harness, pending):  # noqa: F811
    game_id, event = pending
    first = await harness.chat(game_id, ACTION, roll_id=event["roll_id"],
                               invoked_aspects=[HIGH_CONCEPT])
    await harness.drain()
    assert "done" in harness.summarize(first)
    assert await _fate_points(harness, game_id) == 2

    second = await harness.chat(game_id, ACTION, roll_id=event["roll_id"],
                                invoked_aspects=[HIGH_CONCEPT])
    await harness.drain()
    errors = _errors(second)
    assert [e.get("code") for e in errors] == ["roll_not_pending"], second
    assert errors[0]["error"] == "Ce jet n'est plus en attente."
    assert "done" not in harness.summarize(second)
    assert await _fate_points(harness, game_id) == 2


async def test_chat_while_roll_pending_resends_the_modal(harness, pending):  # noqa: F811
    game_id, event = pending
    before = len(await _messages(harness, game_id))
    events = await harness.chat(game_id, "Je fais autre chose.")
    await harness.drain()
    assert harness.summarize(events) == ["roll_pending"]
    again = events[0]
    assert again["roll_id"] == event["roll_id"]
    assert again["roll"] == event["roll"]
    assert again["fate_points"] == 3
    assert HIGH_CONCEPT in again["aspects"]
    assert "mechanical" not in harness.llm.purposes()
    assert len(await _messages(harness, game_id)) == before


async def test_resume_uses_the_stored_message(harness, pending, monkeypatch):  # noqa: F811
    game_id, event = pending
    narration_calls = spy_narration(monkeypatch)
    events = await harness.chat(game_id, "autre chose", roll_id=event["roll_id"],
                                invoked_aspects=[])
    await harness.drain()
    assert "done" in harness.summarize(events)
    sent = str(narration_calls[-1]["messages"])
    assert f"> {ACTION}" in sent and "> autre chose" not in sent
    user_messages = [m["content"] for m in await _messages(harness, game_id) if m["role"] == "user"]
    assert user_messages[-1] == ACTION
    assert "autre chose" not in user_messages


async def test_loaded_state_exposes_pending_roll(harness, pending):  # noqa: F811
    game_id, event = pending
    r = await harness.client.get(f"/api/games/{game_id}", headers=harness.headers)
    assert r.status_code == 200, r.text
    stored = r.json()["state"]["pending_roll"]
    assert stored["roll_id"] == event["roll_id"]
    assert stored["roll"] == event["roll"]
    assert stored["fate_points"] == 3
    assert stored["aspects"] == event["aspects"]

    await harness.chat(game_id, ACTION, roll_id=event["roll_id"], invoked_aspects=[])
    await harness.drain()
    r = await harness.client.get(f"/api/games/{game_id}", headers=harness.headers)
    assert r.json()["state"]["pending_roll"] is None


async def test_overspend_is_rejected_and_fp_unchanged(harness, pending):  # noqa: F811
    game_id, event = pending
    async with harness.pool.acquire() as conn:
        await conn.execute("UPDATE character_fate SET fate_points = 1 WHERE game_id = $1", game_id)
    events = await harness.chat(game_id, ACTION, roll_id=event["roll_id"],
                                invoked_aspects=[HIGH_CONCEPT, TROUBLE])
    await harness.drain()
    errors = _errors(events)
    assert [e.get("code") for e in errors] == ["invalid_invocation"], events
    assert "done" not in harness.summarize(events)
    assert await _fate_points(harness, game_id) == 1
    # The roll is still waiting: the player can choose again.
    r = await harness.client.get(f"/api/games/{game_id}", headers=harness.headers)
    assert r.json()["state"]["pending_roll"]["roll_id"] == event["roll_id"]
