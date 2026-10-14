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


async def test_c13_busy_game_rejected(harness, world_game):
    gate = asyncio.Event()
    original_stream = harness.llm.stream

    async def slow_stream(*a, **k):
        await gate.wait()
        async for x in original_stream(*a, **k):
            yield x

    harness.llm.stream = slow_stream
    first = asyncio.create_task(harness.chat(world_game, "Tour lent."))
    try:
        await asyncio.sleep(0.5)
        second = await harness.chat(world_game, "Tour concurrent.")
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


async def test_c14_missing_api_key(harness, world_game, monkeypatch):
    from api import routes

    async def no_key(pool, user_id, provider_name):
        return None

    monkeypatch.setattr(routes, "_resolve_user_api_key", no_key)
    before = await harness.db_summary(world_game)
    events = await harness.chat(world_game, "Bonjour.")
    await harness.drain()
    after = await harness.db_summary(world_game)
    assert events[0]["type"] == "error" and events[0].get("recoverable") is False
    assert_snapshot("c14_missing_key", {
        "sse": harness.summarize(events),
        "first_event": events[0],
        "llm_calls": harness.llm.purposes(),
        "db_changed": _diff(before, after),
    })


async def test_c15_world_panel(harness, world_game):
    r = await harness.client.get(f"/api/games/{world_game}/world", headers=harness.headers)
    assert r.status_code == 200
    data = r.json()
    assert_snapshot("c15_world_panel", {
        "keys": sorted(data.keys()),
        "counts": {k: len(v) for k, v in sorted(data.items())},
        "item_keys": {k: sorted(v[0].keys()) for k, v in sorted(data.items()) if v},
    })


async def test_c16_provider_error_midstream(harness, world_game):
    before = await harness.db_summary(world_game)
    harness.llm.fail_on["narration"] = RuntimeError("provider down")
    events = await harness.chat(world_game, "Ça va casser.")
    await harness.drain()
    after = await harness.db_summary(world_game)
    errors = [e for e in events if e["type"] == "error"]
    assert errors
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
        await asyncio.sleep(0.3)
    finally:
        gate.set()
    await harness.drain()
    # extraction_logs has no message_id column; the resolver call count is the direct proxy
    # for "an extraction ran for this turn" (one resolver call per non-skipped extraction).
    resolver_calls = harness.llm.purposes().count("resolver")
    assert resolver_calls >= 2, f"only {resolver_calls} extraction(s) ran for 2 turns"
