"""Closing the SSE stream cancels the turn: nothing saved, game lock released (#20)."""

import asyncio
import json
import logging
from uuid import UUID

from api import routes
from api.streaming import SSEEvent, SSEWriter
from config import get_settings
from pipeline import turn
from services.game_service import GameService
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


async def test_disconnect_after_done_does_not_cancel_the_producer():
    """After DONE the turn is committed: background scheduling must still run."""
    writer = SSEWriter()
    task = asyncio.create_task(asyncio.sleep(10))
    writer.attach(task)
    await writer.send_done("Fin.", None)

    stream = writer.iterate()
    await asyncio.wait_for(anext(stream), TIMEOUT)
    await stream.aclose()
    await asyncio.sleep(0.05)

    try:
        assert writer.disconnected is True
        assert not task.done()
    finally:
        task.cancel()


async def test_internal_stream_error_is_logged_as_server_side(caplog):
    writer = SSEWriter()
    task = asyncio.create_task(asyncio.sleep(10))
    writer.attach(task)
    await writer.send(SSEEvent.STATUS, {"bad": object()})  # not JSON-serializable

    with caplog.at_level(logging.INFO, logger="api.streaming"):
        lines = [line async for line in writer.iterate()]

    await asyncio.wait({task}, timeout=1.0)
    assert lines == []
    assert task.cancelled()
    assert "server-side stream error (TypeError)" in caplog.text
    assert "client disconnected" not in caplog.text


async def _game_state(pool, game_id: UUID) -> dict:
    async with pool.acquire() as conn:
        fate_points = await conn.fetchval(
            "SELECT fate_points FROM character_fate WHERE game_id = $1", game_id)
    return {**await _engine_state(pool, game_id), "fate_points": fate_points}


def _rolling_turn_then_plain_turns(harness, gate: asyncio.Event, monkeypatch) -> None:
    """First turn rolls (with stress) and blocks after its first chunk; later turns don't roll."""
    harness.llm._responses["mechanical"] = [
        payloads.mechanical(requires_test=True, skill="Athlétisme", skill_value=2, difficulty=1),
        payloads.mechanical(requires_test=False),
    ]
    _stress_on_every_roll(monkeypatch)
    harness.llm.stream_gate = gate


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


async def _read_all(writer: SSEWriter) -> list[dict]:
    return [json.loads(line[6:]) async for line in writer.iterate() if line.startswith("data: ")]


async def test_disconnect_then_immediate_resend_is_accepted(  # noqa: F811
        harness, fate_game, test_user, monkeypatch):  # noqa: F811
    game_id = UUID(fate_game)
    gate = asyncio.Event()
    _rolling_turn_then_plain_turns(harness, gate, monkeypatch)
    before = await _game_state(harness.pool, game_id)
    settings = get_settings()

    first = routes.start_chat(routes.ChatRequest(message="Je saute.", gameId=game_id),
                              harness.pool, settings, test_user["id"])
    stream = first.iterate()
    await asyncio.wait_for(_read_until_chunk(stream), TIMEOUT)
    await stream.aclose()
    assert routes._get_game_lock(game_id).locked()  # the cancelled turn is still unwinding

    harness.llm.stream_gate = None
    second = routes.start_chat(routes.ChatRequest(message="Je regarde autour.", gameId=game_id),
                               harness.pool, settings, test_user["id"])
    events = await asyncio.wait_for(_read_all(second), TIMEOUT)
    await asyncio.wait_for(harness.drain(), TIMEOUT)

    types = [e["type"] for e in events]
    assert "error" not in types and "done" in types
    assert first._task.cancelled()
    after = await _game_state(harness.pool, game_id)
    assert after["messages"] == before["messages"] + 2  # only the second turn was saved
    assert {**after, "messages": before["messages"]} == before


async def test_http_disconnect_cancels_the_turn(harness, fate_game, monkeypatch):  # noqa: F811
    """Raw ASGI, as uvicorn drives it (HTTP spec 2.3): http.disconnect cancels the turn."""
    from main import app

    game_id = UUID(fate_game)
    gate = asyncio.Event()
    _rolling_turn_then_plain_turns(harness, gate, monkeypatch)
    before = await _game_state(harness.pool, game_id)

    body = json.dumps({"message": "Je saute.", "gameId": str(game_id),
                       "provider": "anthropic"}).encode()
    disconnect = asyncio.Event()
    sent: list[bytes] = []
    received_once = False

    async def receive():
        nonlocal received_once
        if not received_once:
            received_once = True
            return {"type": "http.request", "body": body, "more_body": False}
        await disconnect.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        if message["type"] == "http.response.body":
            sent.append(message.get("body", b""))
            if b'"type": "chunk"' in message.get("body", b""):
                disconnect.set()

    scope = {
        "type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1", "method": "POST", "scheme": "http",
        "path": "/api/chat", "raw_path": b"/api/chat", "query_string": b"", "root_path": "",
        "headers": [(b"host", b"test"), (b"content-type", b"application/json"),
                    (b"authorization", harness.headers["Authorization"].encode())],
        "client": ("127.0.0.1", 12345), "server": ("test", 80),
    }
    await asyncio.wait_for(app(scope, receive, send), TIMEOUT)
    await asyncio.wait_for(harness.drain(), TIMEOUT)

    assert disconnect.is_set()
    assert not any(b'"type": "done"' in chunk for chunk in sent)
    assert routes._get_game_lock(game_id).locked() is False
    assert await _game_state(harness.pool, game_id) == before


async def test_disconnect_during_respond_still_schedules_and_keeps_the_turn(  # noqa: F811
        harness, fate_game, test_user, monkeypatch):  # noqa: F811
    """The turn is committed before respond: a disconnect then cancels nothing (#20)."""
    game_id = UUID(fate_game)
    before = await _game_state(harness.pool, game_id)
    entered, release = asyncio.Event(), asyncio.Event()
    original_load = GameService.load_game_state
    gated = False

    async def gated_load(self, gid):
        nonlocal gated
        if not gated:
            gated = True
            entered.set()
            await release.wait()
        return await original_load(self, gid)

    scheduled: list[str] = []
    original_schedule = turn.schedule_background

    async def spy_schedule(ctx, narrated, committed):
        scheduled.append(narrated.display_text)
        await original_schedule(ctx, narrated, committed)

    monkeypatch.setattr(GameService, "load_game_state", gated_load)
    monkeypatch.setattr(turn, "schedule_background", spy_schedule)

    writer = routes.start_chat(routes.ChatRequest(message="Je regarde autour.", gameId=game_id),
                               harness.pool, get_settings(), test_user["id"])
    stream = writer.iterate()
    await asyncio.wait_for(_read_until_chunk(stream), TIMEOUT)
    await asyncio.wait_for(entered.wait(), TIMEOUT)  # respond is reading the saved state
    await stream.aclose()
    await asyncio.sleep(0.01)
    release.set()

    await asyncio.wait({writer._task}, timeout=TIMEOUT)
    await asyncio.wait_for(harness.drain(), TIMEOUT)
    assert writer._task.cancelled()  # the cancel was delivered...
    assert len(scheduled) == 1  # ...yet extraction/Director were still scheduled
    after = await _game_state(harness.pool, game_id)
    assert after["messages"] == before["messages"] + 2
    assert routes._get_game_lock(game_id).locked() is False
