"""C-12..C-17: rollback/regenerate, busy game, missing key, world panel, provider error, back-to-back turns."""

import asyncio

import pytest

from tests.characterization import payloads
from tests.characterization.snapshot import assert_snapshot


def _brief(messages: list[dict]) -> list[dict]:
    """Stable view of chat messages: role, cycle and a content prefix (no ids)."""
    return [{"role": m["role"], "cycle": m.get("cycle"), "content": m["content"][:40]} for m in messages]


def _diff(a: dict, b: dict) -> dict:
    """Tables whose row count differs between two db_summary results."""
    return {k: [a[k], b[k]] for k in sorted(a) if a[k] != b[k]}


async def _messages(harness, game_id):
    r = await harness.client.get(f"/api/games/{game_id}", headers=harness.headers)
    assert r.status_code == 200, r.text
    return r.json()["messages"]


async def test_c12_rollback_regenerate(harness, world_game):
    # Make the turn visibly grow the KG so the rollback has something to undo.
    harness.llm._responses["resolver"] = payloads.RESOLVER_NEW_CHARACTER
    harness.llm._responses["extract:extract_characters"] = payloads.EXTRACT_CHARACTERS_NEW
    msgs_before_turn = await _messages(harness, world_game)
    db_before_turn = await harness.db_summary(world_game)

    await harness.chat(world_game, "Premier tour.")
    await harness.drain()
    msgs_after_turn = await _messages(harness, world_game)
    db_after_turn = await harness.db_summary(world_game)
    last_user = [m for m in msgs_after_turn if m["role"] == "user"][-1]
    assert last_user["content"] == "Premier tour."

    r = await harness.client.post(f"/api/games/{world_game}/rollback",
                                  json={"messageId": last_user["id"]}, headers=harness.headers)
    assert r.status_code == 200, r.text
    body = r.json()
    msgs_after_rb = await _messages(harness, world_game)
    db_after_rb = await harness.db_summary(world_game)

    assert len(msgs_after_turn) > len(msgs_before_turn)
    assert _brief(msgs_after_rb) == _brief(msgs_before_turn)
    assert_snapshot("c12_rollback", {
        "response_keys": sorted(body.keys()),
        "response_deleted": body["deleted"],
        "response_target_cycle": body["target_cycle"],
        "response_rollback_result": body["rollback_result"],
        "response_state_cycle": body["state"]["game"].get("current_cycle"),
        "messages_before_turn": _brief(msgs_before_turn),
        "messages_after_turn": _brief(msgs_after_turn),
        "messages_after_rollback": _brief(msgs_after_rb),
        "db_before_turn": db_before_turn,
        "db_after_turn": db_after_turn,
        "db_after_rollback": db_after_rb,
        # Tables changed by the turn (before -> after turn) vs by the rollback (after turn -> after rollback)
        "turn_changed": _diff(db_before_turn, db_after_turn),
        "rollback_changed": _diff(db_after_turn, db_after_rb),
        # Tables still different from the pre-turn state once rolled back: NOT restored (#11/#22/#24)
        "not_restored_by_rollback": _diff(db_before_turn, db_after_rb),
    })


async def test_c12b_back_to_arrival_after_day_change_and_new_place(harness, world_game):
    """#11: editing the first message after the arrival, when that turn changed day and
    moved the player to an unknown place (stub location + a fact pointing at it)."""
    import json
    async with harness.pool.acquire() as conn:
        before = await conn.fetchrow(
            """SELECT g.current_cycle, l.name AS location FROM games g
               LEFT JOIN locations l ON l.id = g.current_location_id WHERE g.id = $1""", world_game)
    msgs_before = await _messages(harness, world_game)

    narration = json.loads(payloads.NARRATION)
    narration.update(current_location="Dock 9",
                     day_transition={"new_cycle": 2, "new_date": "Mardi 19 Juillet 2847"})
    harness.llm._responses["narration"] = json.dumps(narration, ensure_ascii=False)
    await harness.chat(world_game, "Je prends la navette vers Dock 9.")
    await harness.drain()
    async with harness.pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO facts (game_id, cycle, type, description, location_id)
               SELECT $1, 1, (SELECT type FROM facts WHERE game_id = $1 LIMIT 1),
                      'Réservation pour Dock 9.', id
               FROM locations WHERE game_id = $1 AND name = 'Dock 9'""", world_game)
        moved = await conn.fetchval("SELECT current_cycle FROM games WHERE id = $1", world_game)
    assert moved == before["current_cycle"] + 1

    first_user = [m for m in await _messages(harness, world_game) if m["role"] == "user"][0]
    r = await harness.client.post(f"/api/games/{world_game}/rollback",
                                  json={"messageId": first_user["id"]}, headers=harness.headers)
    assert r.status_code == 200, r.text

    async with harness.pool.acquire() as conn:
        after = await conn.fetchrow(
            """SELECT g.current_cycle, l.name AS location FROM games g
               LEFT JOIN locations l ON l.id = g.current_location_id WHERE g.id = $1""", world_game)
        dock9 = await conn.fetchval(
            "SELECT COUNT(*) FROM locations WHERE game_id = $1 AND name = 'Dock 9'", world_game)
    assert _brief(await _messages(harness, world_game)) == _brief(msgs_before)
    assert dict(after) == dict(before)
    assert dock9 == 0

    # And the game plays on from the arrival scene.
    harness.llm._responses["narration"] = payloads.NARRATION
    events = await harness.chat(world_game, "Je regarde autour de moi.")
    assert "done" in harness.summarize(events)


async def test_c13_busy_game_rejected(harness, world_game):
    gate = asyncio.Event()
    started = asyncio.Event()
    original_stream = harness.llm.stream

    async def slow_stream(*a, **k):
        started.set()  # the first request holds the game lock once it reaches the LLM
        await gate.wait()
        async for x in original_stream(*a, **k):
            yield x

    harness.llm.stream = slow_stream
    first = asyncio.create_task(harness.chat(world_game, "Tour lent."))
    try:
        await asyncio.wait_for(started.wait(), 30)
        second = await asyncio.wait_for(harness.chat(world_game, "Tour concurrent."), 30)
    except BaseException:
        gate.set()
        first.cancel()
        await asyncio.gather(first, return_exceptions=True)
        raise
    finally:
        gate.set()
    first_events = await first
    await harness.drain()
    assert_snapshot("c13_busy_game", {
        "second_sse": harness.summarize(second),
        "second_first_event": {k: v for k, v in second[0].items()},
        "first_sse": harness.summarize(first_events),
        "messages": _brief(await _messages(harness, world_game))[-2:],
    })
    assert second[0]["type"] == "error" and second[0].get("recoverable") is True


async def test_c14_missing_api_key(harness, world_game, no_api_key):
    before = await harness.db_summary(world_game)
    events = await harness.chat(world_game, "Bonjour.")
    await harness.drain()
    after = await harness.db_summary(world_game)
    assert events[0]["type"] == "error" and events[0].get("recoverable") is False
    assert events[0].get("ref")
    first_event = {k: v for k, v in events[0].items() if k != "ref"}  # ref is the random stream id
    assert_snapshot("c14_missing_key", {
        "sse": harness.summarize(events),
        "first_event": first_event,
        "llm_calls": harness.llm.purposes(),
        "db_changed": _diff(before, after),
    })


async def test_c15_world_panel(harness, world_game):
    r = await harness.client.get(f"/api/games/{world_game}/world", headers=harness.headers)
    assert r.status_code == 200
    data = r.json()
    counts_unknown = {k: len(v) for k, v in sorted(data.items())}
    assert data["npcs"] == []  # the panel lists only characters known by the protagonist
    async with harness.pool.acquire() as conn:
        name = await conn.fetchval(
            "UPDATE characters SET known_by_protagonist = true WHERE id = ("
            "SELECT id FROM characters WHERE game_id = $1 ORDER BY name LIMIT 1) RETURNING name",
            world_game)
    r2 = await harness.client.get(f"/api/games/{world_game}/world", headers=harness.headers)
    npcs = r2.json()["npcs"]
    assert [n["name"] for n in npcs] == [name]
    assert_snapshot("c15_world_panel", {
        "keys": sorted(data.keys()),
        "counts_all_unknown": counts_unknown,
        "counts_one_known": {k: len(v) for k, v in sorted(r2.json().items())},
        "item_keys": {k: sorted(v[0].keys()) for k, v in sorted(data.items()) if v},
        "npc_keys": sorted(npcs[0].keys()),
        "npc": {k: v for k, v in npcs[0].items() if k != "id"},
    })


async def test_c16_provider_error_midstream(harness, world_game):
    before = await harness.db_summary(world_game)
    harness.llm.fail_on["narration"] = RuntimeError("provider down")
    events = await harness.chat(world_game, "Ça va casser.")
    await harness.drain()
    after = await harness.db_summary(world_game)
    errors = [e for e in events if e["type"] == "error"]
    assert errors and all(e.get("ref") for e in errors)
    errors = [{k: v for k, v in e.items() if k != "ref"} for e in errors]  # ref is the random stream id
    msgs = await _messages(harness, world_game)
    assert_snapshot("c16_provider_error", {
        "sse": harness.summarize(events),
        "errors": errors,
        "llm_calls": sorted(harness.llm.purposes()),
        "messages_added": after["messages"] - before["messages"],
        "db_changed": _diff(before, after),
        "last_messages": _brief(msgs)[-2:],
    })
    harness.llm.fail_on.clear()
    recovery = await harness.chat(world_game, "On réessaie.")
    await harness.drain()
    assert "done" in harness.summarize(recovery)


async def test_provider_failure_sends_one_french_error(harness, world_game):
    harness.llm.fail_on["narration"] = RuntimeError("provider down")
    events = await harness.chat(world_game, "Ça va casser.")
    await harness.drain()
    errors = [e for e in events if e["type"] == "error"]
    assert len(errors) == 1
    assert errors[0]["code"] == "provider_error"
    text = str(events)
    assert "Traceback" not in text and "RuntimeError" not in text
    harness.llm.fail_on.clear()
    recovery = await harness.chat(world_game, "On réessaie.")
    await harness.drain()
    assert "done" in harness.summarize(recovery)


@pytest.mark.xfail(strict=True, reason="#17: extraction of turn N+1 is skipped while N runs")
async def test_c17_back_to_back_turns_keep_both_extractions(harness, world_game):
    # Both turns would trigger extraction (resolver reports a new character each time).
    harness.llm._responses["resolver"] = payloads.RESOLVER_NEW_CHARACTER
    harness.llm._responses["extract:extract_characters"] = payloads.EXTRACT_CHARACTERS_NEW
    # Turn A's extraction is held in its resolver call, so it is still running when turn B
    # ends: the realistic overlap (a real LLM resolver takes seconds, turns are quick).
    gate = asyncio.Event()
    first_resolver = {"held": False}

    def hold_first_resolver(method_name):
        original = getattr(harness.llm, method_name)

        async def wrapper(system_prompt, *a, **k):
            from tests.characterization.scripted_llm import classify_call
            if classify_call(system_prompt) == "resolver" and not first_resolver["held"]:
                first_resolver["held"] = True
                await gate.wait()
            return await original(system_prompt, *a, **k)

        setattr(harness.llm, method_name, wrapper)

    for name in ("complete", "complete_with_tools", "complete_with_schema"):
        hold_first_resolver(name)
    try:
        await harness.chat(world_game, "Tour A.")
        await harness.chat(world_game, "Tour B.")  # no drain in between on purpose
    finally:
        gate.set()
    await harness.drain()
    # extraction_logs has no message_id column; the resolver call count is the direct proxy
    # for "an extraction ran for this turn" (one resolver call per non-skipped extraction).
    resolver_calls = harness.llm.purposes().count("resolver")
    assert resolver_calls >= 2, f"only {resolver_calls} extraction(s) ran for 2 turns"
