"""C-07..C-11: narrator deltas, info requests, day transition, extraction, director."""

import json

import pytest

from services import llm_service
from tests.characterization import payloads
from tests.characterization.snapshot import assert_snapshot


def _narration(**extra) -> str:
    data = json.loads(payloads.NARRATION)
    data.update(extra)
    return json.dumps(data, ensure_ascii=False)


async def _turn(harness, game_id, narration_json, message="Je continue."):
    harness.llm._responses["narration"] = narration_json
    events = await harness.chat(game_id, message)
    await harness.drain()
    return events


async def _credits(harness, game_id):
    async with harness.pool.acquire() as conn:
        return await conn.fetchval("SELECT credits FROM protagonists WHERE game_id = $1", game_id)


def _spy_extractor_prompts(harness, monkeypatch) -> dict[str, str]:
    """Record the user prompt each extractor receives, keyed by call label."""
    prompts: dict[str, str] = {}
    original = harness.llm.complete_with_tools

    async def spy(system_prompt, messages, tools, tool_choice, *args, **kwargs):
        prompts[tool_choice.get("name", tools[0]["name"])] = str(messages)
        return await original(system_prompt, messages, tools, tool_choice, *args, **kwargs)

    monkeypatch.setattr(harness.llm, "complete_with_tools", spy)
    return prompts


async def test_c07_credit_and_inventory_deltas(harness, world_game, monkeypatch):
    prompts = _spy_extractor_prompts(harness, monkeypatch)
    harness.llm._responses["extract:extract_inventory"] = {
        "objects_created": [{
            "name": "Gobelet", "canonical_name": "gobelet", "category": "misc",
            "description": "Vide", "from_hint": "Gobelet",
        }],
        "inventory_changes": [{"action": "acquire", "object_hint": "Gobelet", "quantity_delta": 1}],
    }
    before = await _credits(harness, world_game)
    events = await _turn(harness, world_game, _narration(
        credit_delta={"amount": -10, "description": "Un café"},
        inventory_hints=[{"action": "acquire", "item_name": "Gobelet", "item_description": "Vide"}],
        extraction_triggers=["inventory"],
    ), "J'achète un café.")
    after = await _credits(harness, world_game)
    async with harness.pool.acquire() as conn:
        items = await conn.fetch(
            """SELECT o.name, i.quantity FROM inventory i JOIN objects o ON o.id = i.object_id
               WHERE i.game_id = $1 AND o.name = 'Gobelet'""", world_game)
        ledger = await conn.fetch(
            "SELECT name FROM objects WHERE game_id = $1 AND name = 'Gobelet'", world_game)
    done = [e for e in events if e["type"] == "done"][0]
    assert_snapshot("c07_deltas", {
        "sse": harness.summarize(events),
        "credits_before": before,
        "credits_after": after,
        "credits_delta": after - before,
        "client_state_credits": done["state"]["game_state"]["player"]["credits"],
        "client_state_inventory": [i["name"] for i in done["state"]["game_state"]["player"]["inventory"]],
        "inventory": [{"name": r["name"], "quantity": r["quantity"]} for r in items],
        "objects_named_gobelet": len(ledger),
        # The narrator hint only reaches the extractor prompt; the extractor writes the rows.
        "extractor_prompt_has_hint": "Gobelet" in prompts.get("extract_inventory", ""),
        "llm_calls": sorted(harness.llm.purposes()),
    })


async def test_c08_info_requests_prefetch(harness, world_game, monkeypatch):
    seen: list[str] = []
    original = llm_service.LLMService.stream_narration

    async def spy(self, system_prompt, messages, *args, **kwargs):
        seen.append(str(messages[-1]))
        return await original(self, system_prompt, messages, *args, **kwargs)

    monkeypatch.setattr(llm_service.LLMService, "stream_narration", spy)
    header = "### DÉTAILS DEMANDÉS"

    def section(text: str):
        if header not in text:
            return None
        block = text.split(header, 1)[1]
        return block.split("\\n\\n", 1)[0].split("\\n")[:3]

    # Turn A: nothing requested. Turn B: narrator requests a location. Turn C: prefetched
    # details should reach the context. Turn D: no new request (is the request still live?).
    await _turn(harness, world_game, payloads.NARRATION, "Je regarde.")
    await _turn(harness, world_game, _narration(info_requests=["Le Quart de Cycle"]), "Je demande.")
    harness.llm.calls.clear()
    events = await _turn(harness, world_game, payloads.NARRATION, "Je parle au barman.")
    calls_c = sorted(harness.llm.purposes())
    await _turn(harness, world_game, payloads.NARRATION, "Je reste là.")
    async with harness.pool.acquire() as conn:
        stored = await conn.fetchval("SELECT detail_requests FROM games WHERE id = $1", world_game)
    assert len(seen) == 4
    assert_snapshot("c08_info_requests", {
        "sse_turn_c": harness.summarize(events),
        "llm_calls_turn_c": calls_c,
        "stored_detail_requests": stored,
        "details_header_per_turn": [header in s for s in seen],
        "details_section_turn_c": section(seen[2]),
    })


async def test_c09_day_transition(harness, world_game):
    async with harness.pool.acquire() as conn:
        before = await conn.fetchrow(
            'SELECT current_cycle, "current_date" AS d FROM games WHERE id = $1', world_game)
    events = await _turn(harness, world_game, _narration(
        day_transition={"new_cycle": 2, "new_date": "Jour 2", "night_summary": "Une nuit calme."}),
        "Je vais dormir.")
    async with harness.pool.acquire() as conn:
        game = await conn.fetchrow(
            'SELECT current_cycle, "current_date" AS d FROM games WHERE id = $1', world_game)
    done = [e for e in events if e["type"] == "done"]
    errors = [e for e in events if e["type"] == "error"]
    assert not errors, errors
    gs = done[0]["state"]["game_state"]["game"]
    assert_snapshot("c09_day_transition", {
        "sse": harness.summarize(events),
        "cycle_before": before["current_cycle"],
        "cycle": game["current_cycle"],
        "date_before": before["d"],
        "date": game["d"],
        "client_cycle": gs.get("current_cycle"),
        "client_date": gs.get("game_date"),
        "client_time": gs.get("time"),
    })


@pytest.mark.parametrize("bad", [
    {"new_cycle": 2},
    {"new_date": "Jour 2"},
    {"new_cycle": "2", "new_date": "Jour 2", "extra": 1},
    {"new_cycle": 7, "new_date": "Jour 7"},
], ids=["no_date", "no_cycle", "extra_key", "new_cycle_ignored"])
async def test_c09b_day_transition_strictness(harness, world_game, bad, request):
    """Issue #16: record how odd day_transition shapes behave (observation only).

    A missing field discards the whole turn (error event, cycle unchanged); extra keys are
    accepted; the payload's new_cycle value is ignored (cycle becomes current + 1)."""
    events = await _turn(harness, world_game, _narration(day_transition=bad), "Je dors.")
    async with harness.pool.acquire() as conn:
        cycle = await conn.fetchval("SELECT current_cycle FROM games WHERE id = $1", world_game)
    assert_snapshot(f"c09b_day_transition_strictness[{request.node.callspec.id}]", {
        "sse": harness.summarize(events),
        "errors": [" | ".join(e["error"].split("\n")[:2]) for e in events if e["type"] == "error"],  # drop pydantic version URL
        "cycle": cycle,
    })


async def test_c10_extraction_writes_entities(harness, world_game):
    harness.llm._responses["resolver"] = payloads.RESOLVER_NEW_CHARACTER
    harness.llm._responses["extract:extract_characters"] = payloads.EXTRACT_CHARACTERS_NEW
    events = await _turn(harness, world_game, payloads.NARRATION, "J'observe la foule.")
    async with harness.pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT name, occupation FROM characters WHERE game_id = $1 AND name = $2",
            world_game, payloads.NEW_CHARACTER_NAME)
        registry = await conn.fetch(
            "SELECT name, entity_type FROM entity_registry WHERE game_id = $1 AND name = $2",
            world_game, payloads.NEW_CHARACTER_NAME)
    calls = sorted(harness.llm.purposes())
    assert "resolver" in calls and "extract:extract_characters" in calls, calls
    assert_snapshot("c10_extraction", {
        "sse": harness.summarize(events),
        "llm_calls": calls,
        "characters": [dict(r) for r in rows],
        "registry": [dict(r) for r in registry],
        "db_counts": await harness.db_summary(world_game),
    })


async def test_c11_director_plan_written(harness, world_game):
    harness.llm.calls.clear()
    per_turn = []
    for msg in ("Premier tour.", "Deuxième tour.", "Troisième tour."):
        harness.llm.calls.clear()
        await _turn(harness, world_game, payloads.NARRATION, msg)
        per_turn.append(harness.llm.purposes().count("director"))
    async with harness.pool.acquire() as conn:
        plans = await conn.fetch(
            """SELECT tension_level, narrator_guidance, planned_events, long_term_vision, ig_time
               FROM director_plans WHERE game_id = $1 ORDER BY created_at""", world_game)
        last_time = await conn.fetchval(
            "SELECT last_director_time FROM games WHERE id = $1", world_game)
    assert_snapshot("c11_director", {
        "director_calls_per_turn": per_turn,  # #9: runs every turn (last_director_time never loaded)
        "plans": [
            {"tension_level": p["tension_level"], "narrator_guidance": p["narrator_guidance"],
             "planned_events": p["planned_events"], "long_term_vision": p["long_term_vision"],
             "ig_time": p["ig_time"]} for p in plans],
        "last_director_time": last_time,
    })
