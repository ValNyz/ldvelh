"""Closing the SSE stream cancels the turn: nothing saved, game lock released (#20)."""

import asyncio
import json
import logging
from uuid import UUID

from api import game_writers, routes
from api.streaming import SSEEvent, SSEWriter
from config import get_settings
from pipeline import director_runs, turn
from repos import turns
from repos.games import get_snapshot
from services.game_service import GameService
from tests.characterization import payloads
from tests.helpers import engine_state, stress_on_every_roll
from workers import game_locks

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
    assert len(lines) == 1  # the client is told, once, before the stream closes
    error = json.loads(lines[0][6:])
    assert error["type"] == "error"
    assert (error["code"], error["ref"], error["recoverable"]) == ("internal", writer.stream_id, True)
    assert error["error"].startswith("Erreur interne (réf. ")
    assert task.cancelled()
    assert "server-side stream error (TypeError)" in caplog.text
    assert "client disconnected" not in caplog.text


async def _game_state(pool, game_id: UUID) -> dict:
    async with pool.acquire() as conn:
        fate_points = await conn.fetchval(
            "SELECT fate_points FROM character_fate WHERE game_id = $1", game_id)
    return {**await engine_state(pool, game_id), "fate_points": fate_points}


def _rolling_turn_then_plain_turns(harness, gate: asyncio.Event, monkeypatch) -> None:
    """First turn rolls (with stress) and blocks after its first chunk; later turns don't roll."""
    harness.llm._responses["mechanical"] = [
        payloads.mechanical(requires_test=True, skill="Athlétisme", skill_value=2, difficulty=1),
        payloads.mechanical(requires_test=False),
    ]
    stress_on_every_roll(monkeypatch)
    harness.llm.stream_gate = gate


async def _read_until_chunk(stream) -> None:
    while True:
        line = await anext(stream)
        if line.startswith("data: ") and json.loads(line[6:])["type"] == "chunk":
            return


async def test_disconnect_mid_stream_saves_nothing_and_releases_the_lock(
        harness, fate_game, test_user, monkeypatch):
    game_id = fate_game
    harness.llm._responses["mechanical"] = payloads.mechanical(
        requires_test=True, skill="Athlétisme", skill_value=2, difficulty=1)
    stress_on_every_roll(monkeypatch)
    before = await engine_state(harness.pool, UUID(game_id))
    gate = asyncio.Event()
    harness.llm.stream_gate = gate

    request = routes.ChatRequest(message="Je saute par-dessus la barrière.",
                                 gameId=game_id, provider="anthropic")
    writer = routes.start_chat(request, harness.pool, get_settings(), test_user["id"])
    stream = writer.iterate()
    await asyncio.wait_for(_read_until_chunk(stream), TIMEOUT)
    await stream.aclose()

    await asyncio.wait_for(harness.drain(), TIMEOUT)
    assert await engine_state(harness.pool, UUID(game_id)) == before
    assert game_locks.is_held(UUID(game_id)) is False

    harness.llm.stream_gate = None
    gate.set()
    events = await asyncio.wait_for(harness.chat(game_id, "Je saute encore."), TIMEOUT)
    await harness.drain()
    assert "done" in [e["type"] for e in events]


async def _read_all(writer: SSEWriter) -> list[dict]:
    return [json.loads(line[6:]) async for line in writer.iterate() if line.startswith("data: ")]


async def test_disconnect_then_immediate_resend_is_accepted(
        harness, fate_game, test_user, monkeypatch):
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
    assert game_locks.is_held(game_id)  # the cancelled turn is still unwinding

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


async def test_http_disconnect_cancels_the_turn(harness, fate_game, monkeypatch):
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
    assert game_locks.is_held(game_id) is False
    assert await _game_state(harness.pool, game_id) == before


async def test_disconnect_during_respond_still_schedules_and_keeps_the_turn(
        harness, fate_game, test_user, monkeypatch):
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
    assert game_locks.is_held(game_id) is False


async def test_disconnect_during_commit_finishes_the_turn(
        harness, fate_game, test_user, monkeypatch):
    """A started commit completes despite a cancel; done/extraction still follow (#20)."""
    game_id = UUID(fate_game)
    before = await _game_state(harness.pool, game_id)
    entered, release = asyncio.Event(), asyncio.Event()
    original_save = turns.save_turn_messages

    async def gated_save(*args, **kwargs):
        entered.set()
        await release.wait()
        return await original_save(*args, **kwargs)

    scheduled: list[str] = []
    original_schedule = turn.schedule_background

    async def spy_schedule(ctx, narrated, committed):
        scheduled.append(narrated.display_text)
        await original_schedule(ctx, narrated, committed)

    monkeypatch.setattr(turns, "save_turn_messages", gated_save)
    monkeypatch.setattr(turn, "schedule_background", spy_schedule)

    writer = routes.start_chat(routes.ChatRequest(message="Je regarde autour.", gameId=game_id),
                               harness.pool, get_settings(), test_user["id"])
    stream = writer.iterate()
    await asyncio.wait_for(_read_until_chunk(stream), TIMEOUT)
    await asyncio.wait_for(entered.wait(), TIMEOUT)  # the commit transaction is open
    await stream.aclose()
    await asyncio.sleep(0.01)
    release.set()

    await asyncio.wait({writer._task}, timeout=TIMEOUT)
    await asyncio.wait_for(harness.drain(), TIMEOUT)
    assert writer._task.cancelled()
    after = await _game_state(harness.pool, game_id)
    assert after["messages"] == before["messages"] + 2
    assert len(scheduled) == 1
    assert game_locks.is_held(game_id) is False


async def test_disconnect_while_sending_world_done_keeps_the_saved_world(
        harness, test_user, monkeypatch):
    """INIT: a disconnect after the save and the Director, while the done payload is built,
    loses nothing: world, engine, character and duration were saved in one transaction (#20, #79)."""
    game_id = UUID(await harness.create_game("fate_core"))
    entered, release = asyncio.Event(), asyncio.Event()
    original_load = GameService.load_game_state

    async def gated_load(self, gid):
        entered.set()
        await release.wait()
        return await original_load(self, gid)

    monkeypatch.setattr(GameService, "load_game_state", gated_load)
    request = routes.ChatRequest(
        message="__INIT__", gameId=game_id, engine="fate_core",
        world_config={"genre": "sci_fi", "difficulty": "moderate", "duration": "short"},
        character_data=payloads.CHARACTER_DATA["fate_core"])
    writer = routes.start_chat(request, harness.pool, get_settings(), test_user["id"])
    stream = writer.iterate()
    await asyncio.wait_for(anext(stream), TIMEOUT)
    await asyncio.wait_for(entered.wait(), TIMEOUT)  # saved, Director done, building done
    await stream.aclose()
    await asyncio.sleep(0.01)
    release.set()

    await asyncio.wait({writer._task}, timeout=TIMEOUT)
    await asyncio.wait_for(harness.drain(), TIMEOUT)
    assert writer._task.cancelled()  # the cancel was delivered (done never sent)...
    async with harness.pool.acquire() as conn:  # ...after everything was already saved
        snapshot = await get_snapshot(conn, game_id)
        duration = await conn.fetchval(
            "SELECT game_duration FROM games WHERE id = $1", game_id)
        fate_rows = await conn.fetchval(
            "SELECT count(*) FROM character_fate WHERE game_id = $1", game_id)
        plans = await conn.fetchval(
            "SELECT count(*) FROM director_plans WHERE game_id = $1", game_id)
    assert (snapshot.world_created, snapshot.engine, duration) == (True, "fate_core", "short")
    assert fate_rows == 1
    assert plans == 1
    assert game_locks.is_held(game_id) is False


async def test_stream_error_after_done_reports_the_turn_as_saved():
    """DONE queued: the turn is committed, so the error must not invite a resend."""
    writer = SSEWriter()
    await writer.send_done("Fin.", None)
    await writer.send(SSEEvent.STATUS, {"bad": object()})

    lines = [line async for line in writer.iterate()]

    error = json.loads(lines[-1][6:])
    assert (error["code"], error["recoverable"]) == ("saved_display_failed", False)
    assert error["ref"] == writer.stream_id


async def test_stream_error_after_world_done_reports_the_world_as_saved():
    """#80: the world generation's done (world=True) gets the world-specific message."""
    writer = SSEWriter()
    await writer.send_done(None, {"game_state": {}}, world=True)
    await writer.send(SSEEvent.STATUS, {"bad": object()})

    lines = [line async for line in writer.iterate()]

    error = json.loads(lines[-1][6:])
    assert (error["code"], error["recoverable"]) == ("saved_display_failed", False)
    assert error["error"].startswith("Ton monde est enregistré")


async def test_world_info_without_the_world_flag_keeps_the_action_wording():
    """Only the explicit flag decides the wording, never the payload content."""
    writer = SSEWriter()
    await writer.send_done("Fin.", {"game_state": {}, "world_info": {"npc_count": 1}})
    await writer.send(SSEEvent.STATUS, {"bad": object()})

    lines = [line async for line in writer.iterate()]

    error = json.loads(lines[-1][6:])
    assert error["code"] == "saved_display_failed"
    assert error["error"].startswith("Ton action est enregistrée")


async def test_writer_entry_removed_when_cancelled_before_first_step(harness, fate_game, test_user):
    game_id = fate_game
    writer = routes.start_chat(routes.ChatRequest(message="Je regarde.", gameId=game_id),
                               harness.pool, get_settings(), test_user["id"])
    writer._task.cancel()  # before the task ran a single step
    await asyncio.wait({writer._task}, timeout=TIMEOUT)

    assert writer._task.cancelled()
    assert game_writers.writers_of(str(game_id)) == []


def _gate_commit(monkeypatch) -> tuple[asyncio.Event, asyncio.Event]:
    """The first commit waits on `release` once its transaction is open (`entered`)."""
    entered, release = asyncio.Event(), asyncio.Event()
    original_save = turns.save_turn_messages
    gated = False

    async def gated_save(*args, **kwargs):
        nonlocal gated
        if not gated:
            gated = True
            entered.set()
            await release.wait()
        return await original_save(*args, **kwargs)

    monkeypatch.setattr(turns, "save_turn_messages", gated_save)
    return entered, release


async def _client_leaves_while_waiting(writer: SSEWriter) -> None:
    """The response task is cancelled while the stream waits for its first event."""
    reading = asyncio.create_task(anext(writer.iterate()))
    await asyncio.sleep(0.01)
    reading.cancel()
    await asyncio.wait({reading, writer._task}, timeout=TIMEOUT)


async def test_cancelled_resend_does_not_make_the_next_request_busy(
        harness, fate_game, test_user, monkeypatch):
    """First turn unwinding (lock held), resend cancelled while queued: a third request passes."""
    game_id = UUID(fate_game)
    settings = get_settings()
    entered, release = _gate_commit(monkeypatch)

    first = routes.start_chat(routes.ChatRequest(message="Je regarde.", gameId=game_id),
                              harness.pool, settings, test_user["id"])
    stream = first.iterate()
    await asyncio.wait_for(_read_until_chunk(stream), TIMEOUT)
    await asyncio.wait_for(entered.wait(), TIMEOUT)
    await stream.aclose()  # the commit finishes despite the cancel: the lock stays held

    resend = routes.start_chat(routes.ChatRequest(message="Je regarde encore.", gameId=game_id),
                               harness.pool, settings, test_user["id"])
    await _client_leaves_while_waiting(resend)
    assert resend._task.cancelled()
    assert game_locks.is_held(game_id)

    third = routes.start_chat(routes.ChatRequest(message="Je sors.", gameId=game_id),
                              harness.pool, settings, test_user["id"])
    release.set()
    events = await asyncio.wait_for(_read_all(third), TIMEOUT)
    await asyncio.wait_for(harness.drain(), TIMEOUT)

    types = [e["type"] for e in events]
    assert "error" not in types and "done" in types, events
    # The registry's done callback was added first, so it has run once this wait returns.
    await asyncio.wait({third._task}, timeout=TIMEOUT)
    assert game_writers.writers_of(str(game_id)) == []


async def test_disconnect_while_waiting_for_a_connection_cancels_the_turn(
        harness, fate_game, test_user, monkeypatch):
    """Exhausted pool at commit time: a disconnect cancels the wait, nothing is saved."""
    game_id = UUID(fate_game)
    before = await _game_state(harness.pool, game_id)
    gate = asyncio.Event()
    harness.llm.stream_gate = gate
    narrated = asyncio.Event()
    original_narrate = turn.narrate

    async def spy_narrate(*args, **kwargs):
        result = await original_narrate(*args, **kwargs)
        narrated.set()
        return result

    monkeypatch.setattr(turn, "narrate", spy_narrate)
    writer = routes.start_chat(routes.ChatRequest(message="Je regarde autour.", gameId=game_id),
                               harness.pool, get_settings(), test_user["id"])
    stream = writer.iterate()
    await asyncio.wait_for(_read_until_chunk(stream), TIMEOUT)
    held = [await harness.pool.acquire() for _ in range(harness.pool.get_max_size())]
    try:
        harness.llm.stream_gate = None
        gate.set()
        # No sleep needed: the turn goes from narrate's return to pool.acquire() without
        # yielding, so it is already blocked on the exhausted pool when this wait returns.
        await asyncio.wait_for(narrated.wait(), TIMEOUT)
        await stream.aclose()
        await asyncio.wait({writer._task}, timeout=TIMEOUT)
        assert writer._task.cancelled()  # done while the pool is still exhausted
    finally:
        for conn in held:
            await harness.pool.release(conn)

    await asyncio.wait_for(harness.drain(), TIMEOUT)
    assert await _game_state(harness.pool, game_id) == before
    assert game_locks.is_held(game_id) is False


async def test_disconnect_during_initial_director_releases_the_lock(
        harness, test_user, monkeypatch):
    """INIT: a client gone during the initial Director does not hold the game lock for it."""
    from pipeline import init_flow

    game_id = UUID(await harness.create_game("fate_core"))
    entered, release = asyncio.Event(), asyncio.Event()
    original_director = init_flow.run_director

    async def gated_director(**kwargs):
        entered.set()
        await release.wait()
        return await original_director(**kwargs)

    monkeypatch.setattr(init_flow, "run_director", gated_director)
    request = routes.ChatRequest(
        message="__INIT__", gameId=game_id, engine="fate_core",
        world_config={"genre": "sci_fi", "difficulty": "moderate", "duration": "short"},
        character_data=payloads.CHARACTER_DATA["fate_core"])
    writer = routes.start_chat(request, harness.pool, get_settings(), test_user["id"])
    stream = writer.iterate()
    await asyncio.wait_for(anext(stream), TIMEOUT)
    await asyncio.wait_for(entered.wait(), TIMEOUT)
    await stream.aclose()

    await asyncio.wait({writer._task}, timeout=TIMEOUT)
    try:
        assert writer._task.cancelled()  # without waiting for the Director...
        assert game_locks.is_held(game_id) is False
    finally:
        release.set()
    await asyncio.wait_for(harness.drain(), TIMEOUT)
    async with harness.pool.acquire() as conn:  # ...which still completes in the background
        snapshot = await get_snapshot(conn, game_id)
        plans = await conn.fetchval(
            "SELECT count(*) FROM director_plans WHERE game_id = $1", game_id)
    assert snapshot.world_created is True
    assert plans == 1


async def test_arrival_waits_for_the_initial_director_left_running_by_a_disconnect(
        harness, test_user, monkeypatch):
    """Client gone during the initial Director, then the arrival: one plan, and the arrival sees it."""
    from pipeline import init_flow
    from tests.characterization.harness import spy_narration

    game_id = UUID(await harness.create_game("fate_core"))
    entered, release = asyncio.Event(), asyncio.Event()
    original_director = init_flow.run_director

    async def gated_director(**kwargs):
        entered.set()
        await release.wait()
        return await original_director(**kwargs)

    monkeypatch.setattr(init_flow, "run_director", gated_director)
    request = routes.ChatRequest(
        message="__INIT__", gameId=game_id, engine="fate_core",
        world_config={"genre": "sci_fi", "difficulty": "moderate", "duration": "short"},
        character_data=payloads.CHARACTER_DATA["fate_core"])
    writer = routes.start_chat(request, harness.pool, get_settings(), test_user["id"])
    stream = writer.iterate()
    await asyncio.wait_for(anext(stream), TIMEOUT)
    await asyncio.wait_for(entered.wait(), TIMEOUT)
    await stream.aclose()
    await asyncio.wait({writer._task}, timeout=TIMEOUT)

    narrations = spy_narration(monkeypatch)
    waiting, waited = asyncio.Event(), asyncio.Event()
    original_wait = director_runs.wait_for_initial

    async def spy_wait(gid):
        waiting.set()  # then blocks in the wait at once: the Director is still gated
        await original_wait(gid)
        waited.set()

    monkeypatch.setattr(director_runs, "wait_for_initial", spy_wait)
    arrival = routes.start_chat(routes.ChatRequest(message="__ARRIVEE__", gameId=game_id),
                                harness.pool, get_settings(), test_user["id"])
    reading = asyncio.create_task(_read_all(arrival))
    await asyncio.wait_for(waiting.wait(), TIMEOUT)
    assert director_runs.is_running(game_id)
    assert not waited.is_set() and narrations == []  # the arrival waits for the plan
    release.set()
    events = await asyncio.wait_for(reading, TIMEOUT)
    await asyncio.wait_for(harness.drain(), TIMEOUT)

    assert waited.is_set()
    assert "done" in [e["type"] for e in events], events
    async with harness.pool.acquire() as conn:
        plans = await conn.fetchval(
            "SELECT count(*) FROM director_plans WHERE game_id = $1", game_id)
    assert plans == 1
    prompt = json.dumps(narrations[0], ensure_ascii=False)  # system + context messages
    assert "Rythme calme, laisser le joueur explorer." in prompt


async def test_disconnect_during_world_save_commits_and_starts_the_director(
        harness, test_user, monkeypatch):
    """A cancel during the world-save transaction: the world is committed and its Director runs."""
    from kg.specialized_populator import WorldPopulator

    game_id = UUID(await harness.create_game("fate_core"))
    entered, release = asyncio.Event(), asyncio.Event()
    original_meta = WorldPopulator._store_generation_meta

    async def gated_meta(self, conn, world_gen):
        entered.set()
        await release.wait()
        return await original_meta(self, conn, world_gen)

    monkeypatch.setattr(WorldPopulator, "_store_generation_meta", gated_meta)
    request = routes.ChatRequest(
        message="__INIT__", gameId=game_id, engine="fate_core",
        world_config={"genre": "sci_fi", "difficulty": "moderate", "duration": "short"},
        character_data=payloads.CHARACTER_DATA["fate_core"])
    writer = routes.start_chat(request, harness.pool, get_settings(), test_user["id"])
    stream = writer.iterate()
    await asyncio.wait_for(anext(stream), TIMEOUT)
    await asyncio.wait_for(entered.wait(), TIMEOUT)  # the world-save transaction is open
    await stream.aclose()  # cancels the task at once: no need to yield before releasing
    release.set()

    await asyncio.wait({writer._task}, timeout=TIMEOUT)
    assert writer._task.cancelled()
    assert game_locks.is_held(game_id) is False
    await asyncio.wait_for(harness.drain(), TIMEOUT)
    async with harness.pool.acquire() as conn:
        snapshot = await get_snapshot(conn, game_id)
        fate_rows = await conn.fetchval(
            "SELECT count(*) FROM character_fate WHERE game_id = $1", game_id)
        plans = await conn.fetchval(
            "SELECT count(*) FROM director_plans WHERE game_id = $1", game_id)
    assert (snapshot.world_created, snapshot.engine, fate_rows) == (True, "fate_core", 1)
    assert plans == 1
