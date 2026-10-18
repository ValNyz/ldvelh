"""Rollback vs background jobs (#23): rollback cancels the game's jobs, and a job that
outlives the cancel writes nothing once its source message is gone (no ghost entities)."""

import asyncio
import logging
import time
from uuid import UUID

import pytest

from config import get_settings
from services.extraction.characters import CharactersExtractor
from tests.characterization import payloads
from tests.characterization.scripted_llm import classify_call
from tests.helpers import rollback_last_turn
from workers import supervisor

pytestmark = pytest.mark.integration

TIMEOUT = 10.0


def _brief(messages: list[dict]) -> list[tuple]:
    return [(m["role"], m["content"]) for m in messages]


async def _messages(harness, game_id):
    r = await harness.client.get(f"/api/games/{game_id}", headers=harness.headers)
    assert r.status_code == 200, r.text
    return r.json()["messages"]


async def _new_character_count(harness, game_id) -> int:
    async with harness.pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT COUNT(*) FROM characters WHERE game_id = $1 AND name = $2",
            game_id, payloads.NEW_CHARACTER_NAME)


def _script_new_character(harness):
    harness.llm._responses["resolver"] = payloads.RESOLVER_NEW_CHARACTER
    harness.llm._responses["extract:extract_characters"] = payloads.EXTRACT_CHARACTERS_NEW


def _hold_first_resolver(harness) -> tuple[asyncio.Event, asyncio.Event]:
    """The first resolver call waits on `gate` (as in C-17); `entered` is set once it does."""
    gate, entered = asyncio.Event(), asyncio.Event()
    held = {"done": False}

    def wrap(method_name):
        original = getattr(harness.llm, method_name)

        async def wrapper(system_prompt, *a, **k):
            if classify_call(system_prompt) == "resolver" and not held["done"]:
                held["done"] = True
                entered.set()
                await gate.wait()
            return await original(system_prompt, *a, **k)

        setattr(harness.llm, method_name, wrapper)

    for name in ("complete", "complete_with_tools", "complete_with_schema"):
        wrap(name)
    return gate, entered


async def test_rollback_cancels_the_running_extraction(harness, world_game):
    _script_new_character(harness)
    gate, entered = _hold_first_resolver(harness)
    msgs_before = await _messages(harness, world_game)
    try:
        await harness.chat(world_game, "Premier tour.")  # no drain: the job stays blocked
        await asyncio.wait_for(entered.wait(), TIMEOUT)
        assert supervisor.pending(UUID(world_game)) == 1  # the job's _jobs key is the UUID
        await rollback_last_turn(harness, world_game)
        assert supervisor.pending(UUID(world_game)) == 0
    finally:
        gate.set()
    await harness.drain()

    assert await _new_character_count(harness, world_game) == 0
    assert _brief(await _messages(harness, world_game)) == _brief(msgs_before)


async def test_regenerate_extracts_the_replacement_turn(harness, world_game):
    _script_new_character(harness)
    gate, entered = _hold_first_resolver(harness)
    try:
        await harness.chat(world_game, "Premier tour.")
        await asyncio.wait_for(entered.wait(), TIMEOUT)
        harness.llm.calls.clear()
        await rollback_last_turn(harness, world_game)
        await harness.chat(world_game, "Tour de remplacement.")
    finally:
        gate.set()
    await harness.drain()

    assert harness.llm.purposes().count("resolver") >= 1
    assert await _new_character_count(harness, world_game) == 1


async def test_job_past_the_cancel_timeout_writes_nothing(harness, world_game, monkeypatch,
                                                         caplog):
    # Patched on the cached Settings object the route reads through get_settings_dep.
    monkeypatch.setattr(get_settings(), "supervisor_cancel_timeout", 0.05)
    _script_new_character(harness)
    release, entered = asyncio.Event(), asyncio.Event()

    async def stubborn_call_llm(self, system_prompt, user_prompt, schema):
        entered.set()
        while not release.is_set():  # same loop as uncancellable._wait_ignoring_cancel
            try:
                await release.wait()
            except asyncio.CancelledError:
                continue
        return payloads.EXTRACT_CHARACTERS_NEW, None

    results: list[dict] = []
    real_run = CharactersExtractor.run

    async def recording_run(self, *a, **k):
        result = await real_run(self, *a, **k)
        results.append(result)
        return result

    monkeypatch.setattr(CharactersExtractor, "_call_llm", stubborn_call_llm)
    monkeypatch.setattr(CharactersExtractor, "run", recording_run)
    try:
        await harness.chat(world_game, "Premier tour.")
        await asyncio.wait_for(entered.wait(), TIMEOUT)
        with caplog.at_level(logging.ERROR, logger="workers.supervisor"):
            started = time.monotonic()
            await rollback_last_turn(harness, world_game)  # 200 although the job lives on
            elapsed = time.monotonic() - started
        assert "still running after cancel" in caplog.text
        assert elapsed < 2.0  # the 0.05 s cancel timeout was used, not the 10 s default
    finally:
        release.set()
    await harness.drain()

    assert [r.get("skipped") for r in results] == [True]
    assert results[0]["error"] == "source_message_gone"
    assert await _new_character_count(harness, world_game) == 0


async def test_rejected_rollback_still_returns_400(harness, world_game):
    """The cancel runs before the service validates: an arrival-scene rollback is still a
    400 (and has cancelled the in-flight extraction, the documented trade-off)."""
    _script_new_character(harness)
    gate, entered = _hold_first_resolver(harness)
    try:
        await harness.chat(world_game, "Premier tour.")
        await asyncio.wait_for(entered.wait(), TIMEOUT)
        assert supervisor.pending(UUID(world_game)) == 1
        msgs_before = await _messages(harness, world_game)
        r = await harness.client.post(f"/api/games/{world_game}/rollback",
                                      json={"fromIndex": 0}, headers=harness.headers)
        assert r.status_code == 400, r.text
        assert r.json()["detail"] == "Impossible de revenir avant la scène d'arrivée."
        assert supervisor.pending(UUID(world_game)) == 0
    finally:
        gate.set()
    await harness.drain()
    assert _brief(await _messages(harness, world_game)) == _brief(msgs_before)
