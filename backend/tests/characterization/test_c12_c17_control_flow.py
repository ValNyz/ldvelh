"""C-12..C-17: rollback/regenerate, busy game, missing key, world panel, provider error, back-to-back turns."""

import asyncio

import pytest

from tests.characterization import payloads
from tests.characterization.snapshot import assert_snapshot
from tests.helpers import narration_with, rollback_last_turn

_DAY_CHANGE = {"new_cycle": 2, "new_date": "Mardi 19 Juillet 2847"}


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
    harness.llm._responses["identity"] = payloads.IDENTITY_NEW_CHARACTER
    harness.llm._responses["narration"] = payloads.NARRATION_NEW_CHARACTER
    harness.llm._responses["extract:extract_characters"] = payloads.extract_characters_new
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
    async with harness.pool.acquire() as conn:
        before = await conn.fetchrow(
            """SELECT g.current_cycle, l.name AS location FROM games g
               LEFT JOIN locations l ON l.id = g.current_location_id WHERE g.id = $1""", world_game)
    msgs_before = await _messages(harness, world_game)

    harness.llm._responses["narration"] = narration_with(
        current_location="Dock 9",
        day_transition={"new_cycle": 2, "new_date": "Mardi 19 Juillet 2847"})
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


async def test_c12e_rollback_keeps_initial_director_arc(harness):
    """#85 (test B): the initial Director creates an arc before the first turn; two turns
    at cycle 1, then rolling back only the last one must keep that arc (it was deleted
    when arcs were rolled back by chronology.created_at)."""
    import json
    title = "Arc du Directeur"
    harness.llm._responses["director"] = json.dumps({**json.loads(payloads.DIRECTOR), "arc_updates": [
        {"action": "create", "title": title, "description": "Posé avant le premier tour."}]})
    game_id = await harness.create_game("none")
    await harness.init_world(game_id)
    await harness.chat(game_id, "__ARRIVEE__")
    await harness.drain()
    harness.llm._responses["director"] = payloads.DIRECTOR

    for msg in ("Premier tour.", "Deuxième tour."):
        await harness.chat(game_id, msg)
        await harness.drain()
    msgs = await _messages(harness, game_id)
    assert {m["cycle"] for m in msgs} == {1}
    last_user = [m for m in msgs if m["role"] == "user"][-1]
    count_sql = "SELECT COUNT(*) FROM narrative_arcs WHERE game_id = $1 AND title = $2"
    async with harness.pool.acquire() as conn:
        assert await conn.fetchval(count_sql, game_id, title) == 1

    r = await harness.client.post(f"/api/games/{game_id}/rollback",
                                  json={"messageId": last_user["id"]}, headers=harness.headers)
    assert r.status_code == 200, r.text
    assert r.json()["target_cycle"] == 1
    async with harness.pool.acquire() as conn:
        kept = await conn.fetchval(count_sql, game_id, title)
        stamped = await conn.fetchval(
            "SELECT created_cycle FROM narrative_arcs WHERE game_id = $1 AND title = $2",
            game_id, title)
    assert kept == 1
    assert stamped == 1  # the cycle the initial Director ran for


async def test_c12f_arc_insert_without_created_cycle_fails(harness, world_game):
    """#85: created_cycle has no default, so a writer that forgets it fails instead of
    writing an arc no rollback would ever remove."""
    import asyncpg
    async with harness.pool.acquire() as conn:
        with pytest.raises(asyncpg.NotNullViolationError):
            await conn.execute(
                "INSERT INTO narrative_arcs (game_id, title) VALUES ($1, 'Sans cycle')",
                world_game)


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
        # ref is the random stream id (#80: the rejection carries one, like any error)
        "second_first_event": {k: v for k, v in second[0].items() if k != "ref"},
        "first_sse": harness.summarize(first_events),
        "messages": _brief(await _messages(harness, world_game))[-2:],
    })
    assert second[0]["type"] == "error" and second[0].get("recoverable") is True
    assert second[0].get("ref")


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
    # #45: one French error with its code, no raw exception text, then a playable game.
    assert len(errors) == 1 and errors[0]["code"] == "provider_error" and errors[0].get("ref")
    assert "Traceback" not in str(events) and "RuntimeError" not in str(events)
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


async def test_c17_back_to_back_turns_keep_both_resolutions(harness, world_game):
    # Both turns name the new character: the first creates her, the second links her.
    harness.llm._responses["identity"] = payloads.IDENTITY_NEW_CHARACTER
    harness.llm._responses["narration"] = payloads.NARRATION_NEW_CHARACTER
    harness.llm._responses["extract:extract_characters"] = payloads.extract_characters_new
    # Turn A's extraction is held in its resolver call, so it is still running when turn B
    # ends: the realistic overlap (a real LLM resolver takes seconds, turns are quick).
    gate = asyncio.Event()
    first_resolver = {"held": False}

    def hold_first_resolver(method_name):
        original = getattr(harness.llm, method_name)

        async def wrapper(system_prompt, *a, **k):
            from tests.characterization.scripted_llm import classify_call
            if classify_call(system_prompt) == "identity" and not first_resolver["held"]:
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
    # One identity call per resolved turn, and each turn keeps its own mentions (#154).
    resolver_calls = harness.llm.purposes().count("identity")
    assert resolver_calls >= 2, f"only {resolver_calls} resolution(s) ran for 2 turns"
    async with harness.pool.acquire() as conn:
        per_message = await conn.fetch(
            """SELECT m.id, count(em.id) AS mentions
                 FROM messages AS m
                 LEFT JOIN entity_mentions AS em ON em.message_id = m.id
                WHERE m.game_id = $1 AND m.role = 'assistant'
                GROUP BY m.id, m.sequence ORDER BY m.sequence DESC LIMIT 2""",
            world_game)
        created = await conn.fetchval(
            "SELECT count(*) FROM characters WHERE game_id = $1 AND name = $2",
            world_game, payloads.NEW_CHARACTER_NAME)
    assert [r["mentions"] > 0 for r in per_message] == [True, True]
    assert created == 1


async def test_c12c_day_change_turn_with_roll_rolls_back_cleanly(harness, fate_game, monkeypatch):
    """#134: a day-change turn with a roll leaves no roll effect (stress, roll history) after
    its player message is rolled back."""
    from tests.helpers import engine_state, stress_on_every_roll
    stress_on_every_roll(monkeypatch)
    before = await engine_state(harness.pool, fate_game)
    harness.llm._responses["mechanical"] = payloads.mechanical(
        requires_test=True, skill="Athlétisme", skill_value=2, difficulty=1)
    harness.llm._responses["narration"] = narration_with(day_transition=_DAY_CHANGE)
    await harness.chat(fate_game, "Je dors après un effort.")
    await harness.drain()
    during = await engine_state(harness.pool, fate_game)
    assert during["cycle"] == before["cycle"] + 1
    assert during["stress"] != before["stress"] and during["rolls"] == before["rolls"] + 1
    async with harness.pool.acquire() as conn:
        roll_cycle = await conn.fetchval(
            "SELECT cycle FROM mechanic_rolls WHERE game_id = $1 AND status = 'resolved'"
            " ORDER BY created_at DESC LIMIT 1", fate_game)
    assert roll_cycle == during["cycle"]

    await rollback_last_turn(harness, fate_game)
    assert await engine_state(harness.pool, fate_game) == before


async def test_c12d_resumed_roll_on_day_change_turn_rolls_back_cleanly(harness, pending):
    """#134: the pending roll is stored at the pre-turn cycle; resolved on a day-change turn it
    is re-stamped with the post-turn one, so the rollback of that turn removes it."""
    game_id, event = pending
    async with harness.pool.acquire() as conn:
        fate_points = await conn.fetchval(
            "SELECT fate_points FROM character_fate WHERE game_id = $1", game_id)
    harness.llm._responses["narration"] = narration_with(day_transition=_DAY_CHANGE)
    await harness.chat(game_id, "Je tente un saut impossible.", roll_id=event["roll_id"],
                       invoked_aspects=["Pilote déchu en quête de rédemption"])
    await harness.drain()
    async with harness.pool.acquire() as conn:
        resolved = await conn.fetchrow(
            "SELECT cycle FROM mechanic_rolls WHERE id = $1::uuid AND status = 'resolved'",
            event["roll_id"])
        game_cycle = await conn.fetchval("SELECT current_cycle FROM games WHERE id = $1", game_id)
    assert resolved is not None and resolved["cycle"] == game_cycle

    await rollback_last_turn(harness, game_id)
    async with harness.pool.acquire() as conn:
        left = await conn.fetchval("SELECT count(*) FROM mechanic_rolls WHERE id = $1::uuid",
                                   event["roll_id"])
        restored = await conn.fetchval(
            "SELECT fate_points FROM character_fate WHERE game_id = $1", game_id)
    assert left == 0
    assert restored == fate_points  # the invocation's fate point is refunded
