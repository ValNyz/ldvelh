"""Closing the SSE stream cancels the turn: nothing saved, game lock released (#20)."""

import asyncio
import json
from uuid import UUID

from api import routes
from api.streaming import SSEWriter
from config import get_settings
from tests.characterization import payloads
from tests.characterization.conftest import harness, llm_mode, scripted_llm  # noqa: F401
from tests.pipeline.test_commit import _engine_state, _stress_on_every_roll, fate_game  # noqa: F401

TIMEOUT = 5.0


async def test_send_after_disconnect_does_not_enqueue():
    writer = SSEWriter()
    writer.disconnected = True

    await writer.send_chunk("x")

    assert writer._queue.empty()


async def test_closing_the_stream_cancels_the_producer():
    writer = SSEWriter()
    task = asyncio.create_task(asyncio.sleep(10))
    writer.attach(task)
    await writer.send_status("narrating")

    stream = writer.iterate()
    first = await asyncio.wait_for(anext(stream), TIMEOUT)
    assert first.startswith("data: ")
    await stream.aclose()

    await asyncio.wait({task}, timeout=1.0)
    assert task.cancelled()
    assert writer.disconnected is True


async def _read_until_chunk(stream) -> None:
    while True:
        line = await anext(stream)
        if line.startswith("data: ") and json.loads(line[6:])["type"] == "chunk":
            return


async def test_disconnect_mid_stream_saves_nothing_and_releases_the_lock(  # noqa: F811
        harness, fate_game, test_user, monkeypatch):  # noqa: F811
    game_id = fate_game
    harness.llm._responses["mechanical"] = payloads.mechanical(
        requires_test=True, skill="Athlétisme", skill_value=2, difficulty=1)
    _stress_on_every_roll(monkeypatch)
    before = await _engine_state(harness.pool, UUID(game_id))
    gate = asyncio.Event()
    harness.llm.stream_gate = gate

    request = routes.ChatRequest(message="Je saute par-dessus la barrière.",
                                 gameId=game_id, provider="anthropic")
    writer = routes.start_chat(request, harness.pool, get_settings(), test_user["id"])
    stream = writer.iterate()
    await asyncio.wait_for(_read_until_chunk(stream), TIMEOUT)
    await stream.aclose()

    await asyncio.wait_for(harness.drain(), TIMEOUT)
    assert await _engine_state(harness.pool, UUID(game_id)) == before
    assert routes._get_game_lock(UUID(game_id)).locked() is False

    harness.llm.stream_gate = None
    gate.set()
    events = await asyncio.wait_for(harness.chat(game_id, "Je saute encore."), TIMEOUT)
    await harness.drain()
    assert "done" in [e["type"] for e in events]
